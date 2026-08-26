#!/usr/bin/env python3
"""
Zendesk Watch Agent
Queries Zendesk tickets, extracts vendor alerts, and analyzes them with Groq.
"""

import os
import csv
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
import re

import requests
from dotenv import load_dotenv
from groq import Groq

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
ZENDESK_SUBDOMAIN = os.getenv('ZENDESK_SUBDOMAIN')
ZENDESK_EMAIL = os.getenv('ZENDESK_EMAIL')
ZENDESK_API_TOKEN = os.getenv('ZENDESK_API_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Vendor and alert keywords
VENDOR_KEYWORDS = {
    "twilio": ["twilio", "sms", "messaging", "sendgrid"],
    "entrust": ["entrust", "card", "payment", "x-pays", "ssl"],
    "jumio": ["jumio", "kyc", "identity", "verification"],
}

ALERT_KEYWORDS = [
    "deprecation", "deprecated", "breaking change",
    "security", "vulnerability", "compliance",
    "sunset", "eol", "end of life", "upgrade",
    "deadline", "expires", "expiry", "urgent",
    "critical", "action required", "api change"
]

OUTPUT_FILE = "zendesk_watch_agent_alerts.csv"
CSV_COLUMNS = [
    "vendor", "product", "title", "type", "priority", "status",
    "ticket_id", "ticket_url", "created_at", "deadline_date",
    "days_until_deadline", "urgency_badge", "action_priority",
    "impact_summary", "backbase_action_required", "backbase_rationale", "logged_at"
]


def get_zendesk_headers() -> Dict[str, str]:
    """Create Zendesk API headers with Basic Auth."""
    auth_string = f"{ZENDESK_EMAIL}/token:{ZENDESK_API_TOKEN}"
    auth_bytes = auth_string.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

    return {
        'Authorization': f'Basic {auth_b64}',
        'Content-Type': 'application/json'
    }


def fetch_zendesk_tickets() -> List[Dict]:
    """Fetch ALL tickets from Zendesk using pagination."""
    if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
        logger.error("Missing Zendesk credentials in .env file")
        return []

    all_tickets = []
    base_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com"
    url = urljoin(base_url, "/api/v2/tickets.json")
    headers = get_zendesk_headers()
    params = {"per_page": 100}

    try:
        page = 1
        while url:
            logger.info(f"Fetching page {page}...")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            tickets = data.get('tickets', [])
            all_tickets.extend(tickets)

            # Get next page URL
            url = data.get('next_page')
            page += 1

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Zendesk tickets: {e}")
        return all_tickets

    logger.info(f"✅ Fetched {len(all_tickets)} total tickets")
    return all_tickets


def contains_vendor_keyword(text: str) -> Optional[str]:
    """Check if text contains vendor keywords. Returns vendor name or None."""
    text_lower = text.lower()
    for vendor, keywords in VENDOR_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return vendor
    return None


def contains_alert_keyword(text: str) -> bool:
    """Check if text contains alert keywords."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in ALERT_KEYWORDS)


def filter_vendor_alert_tickets(tickets: List[Dict]) -> List[Dict]:
    """Filter tickets matching both vendor and alert keywords."""
    filtered = []

    for ticket in tickets:
        subject = ticket.get('subject', '')
        description = ticket.get('description', '')
        combined_text = f"{subject} {description}"

        vendor = contains_vendor_keyword(combined_text)
        has_alert = contains_alert_keyword(combined_text)

        if vendor and has_alert:
            ticket['detected_vendor'] = vendor
            filtered.append(ticket)

    logger.info(f"📋 {len(filtered)} tickets match both vendor and alert keywords")
    return filtered


def extract_deadline_from_text(text: str) -> Optional[str]:
    """Extract deadline/expiry date from text using regex patterns."""
    if not text:
        return None

    # Common date patterns: YYYY-MM-DD, MM/DD/YYYY, Month DD, YYYY, etc.
    patterns = [
        r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def calculate_days_until_deadline(deadline_str: Optional[str]) -> Tuple[Optional[int], str]:
    """Calculate days until deadline and return urgency badge."""
    if not deadline_str:
        return None, "UNKNOWN"

    try:
        # Try parsing various date formats
        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y', '%b %d, %Y']:
            try:
                deadline = datetime.strptime(deadline_str, fmt).date()
                days = (deadline - datetime.now().date()).days

                if days < 0:
                    return days, "OVERDUE"
                elif days <= 7:
                    return days, "CRITICAL"
                elif days <= 30:
                    return days, "WARNING"
                else:
                    return days, "NORMAL"
            except ValueError:
                continue

        return None, "UNKNOWN"
    except Exception as e:
        logger.warning(f"Error parsing deadline: {e}")
        return None, "UNKNOWN"


def parse_zendesk_ticket(ticket: Dict) -> Dict:
    """Parse and extract information from a Zendesk ticket."""
    ticket_id = ticket.get('id')
    subject = ticket.get('subject', '')
    description = ticket.get('description', '')
    created_at = ticket.get('created_at', '')
    updated_at = ticket.get('updated_at', '')
    priority = ticket.get('priority', 'normal')
    status = ticket.get('status', 'open')
    tags = ticket.get('tags', [])

    vendor = ticket.get('detected_vendor', 'unknown')

    # Extract deadline from description
    deadline_str = extract_deadline_from_text(description)
    days_until, urgency = calculate_days_until_deadline(deadline_str)

    # Determine alert type
    alert_type = "unknown"
    if any(kw in description.lower() + subject.lower() for kw in ["deprecation", "deprecated"]):
        alert_type = "deprecation"
    elif any(kw in description.lower() + subject.lower() for kw in ["security", "vulnerability"]):
        alert_type = "security"
    elif any(kw in description.lower() + subject.lower() for kw in ["compliance"]):
        alert_type = "compliance"
    elif any(kw in description.lower() + subject.lower() for kw in ["sunset", "eol", "end of life"]):
        alert_type = "sunset"
    elif any(kw in description.lower() + subject.lower() for kw in ["upgrade"]):
        alert_type = "upgrade"

    ticket_url = f"https://backbase.zendesk.com/agent/tickets/{ticket_id}"

    # Calculate days since created
    try:
        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        days_since_created = (datetime.now(created.tzinfo) - created).days
    except:
        days_since_created = None

    return {
        'ticket_id': ticket_id,
        'subject': subject,
        'description': description,
        'created_at': created_at,
        'updated_at': updated_at,
        'priority': priority,
        'status': status,
        'tags': tags,
        'vendor': vendor,
        'alert_type': alert_type,
        'deadline_date': deadline_str,
        'days_until_deadline': days_until,
        'urgency_badge': urgency,
        'ticket_url': ticket_url,
        'days_since_created': days_since_created
    }


def analyze_zendesk_alert(parsed_ticket: Dict) -> Optional[Dict]:
    """Use Groq to analyze ticket content and determine impact."""
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not found in .env, skipping AI analysis")
        return None

    client = Groq()

    prompt = f"""Analyze this Zendesk ticket and provide a JSON response with the following fields:
- impact_summary: Brief summary of impact (max 100 chars)
- backbase_action_required: What action Backbase should take (max 150 chars)
- backbase_rationale: Why this action is important (max 150 chars)

Ticket Info:
Vendor: {parsed_ticket['vendor']}
Subject: {parsed_ticket['subject']}
Alert Type: {parsed_ticket['alert_type']}
Deadline: {parsed_ticket['deadline_date']}
Urgency: {parsed_ticket['urgency_badge']}

Description:
{parsed_ticket['description'][:1000]}

Response must be valid JSON only, no markdown."""

    try:
        message = client.messages.create(
            model="mixtral-8x7b-32768",
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text.strip()

        # Parse JSON response
        try:
            analysis = json.loads(response_text)
            return analysis
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Groq response as JSON: {response_text}")
            return None

    except Exception as e:
        logger.warning(f"Error calling Groq API: {e}")
        return None


def process_ticket(ticket: Dict) -> Optional[Dict]:
    """Process a single ticket: parse and analyze."""
    parsed = parse_zendesk_ticket(ticket)
    analysis = analyze_zendesk_alert(parsed)

    if analysis is None:
        analysis = {
            'impact_summary': 'Requires manual review',
            'backbase_action_required': 'Review ticket for action items',
            'backbase_rationale': 'Vendor alert detected'
        }

    # Determine action priority based on urgency
    if parsed['urgency_badge'] == 'OVERDUE':
        action_priority = 'CRITICAL'
    elif parsed['urgency_badge'] == 'CRITICAL':
        action_priority = 'HIGH'
    elif parsed['urgency_badge'] == 'WARNING':
        action_priority = 'MEDIUM'
    else:
        action_priority = 'LOW'

    return {
        'vendor': parsed['vendor'],
        'product': parsed['vendor'].capitalize(),  # Simplified; could extract more specifically
        'title': parsed['subject'],
        'type': parsed['alert_type'],
        'priority': parsed['priority'],
        'status': parsed['status'],
        'ticket_id': parsed['ticket_id'],
        'ticket_url': parsed['ticket_url'],
        'created_at': parsed['created_at'],
        'deadline_date': parsed['deadline_date'] or 'Not specified',
        'days_until_deadline': parsed['days_until_deadline'],
        'urgency_badge': parsed['urgency_badge'],
        'action_priority': action_priority,
        'impact_summary': analysis.get('impact_summary', 'Requires review'),
        'backbase_action_required': analysis.get('backbase_action_required', 'Review ticket'),
        'backbase_rationale': analysis.get('backbase_rationale', 'Vendor alert detected'),
        'logged_at': datetime.now().isoformat()
    }


def load_existing_alerts() -> set:
    """Load existing ticket IDs from CSV to avoid duplicates."""
    if not os.path.exists(OUTPUT_FILE):
        return set()

    existing_ids = set()
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_ids.add(str(row.get('ticket_id', '')))
    except Exception as e:
        logger.warning(f"Error reading existing alerts: {e}")

    return existing_ids


def save_alerts_to_file(alerts: List[Dict]) -> None:
    """Save alerts to CSV file."""
    if not alerts:
        logger.info("No alerts to save")
        return

    try:
        file_exists = os.path.exists(OUTPUT_FILE)

        with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)

            # Write header only if file is new
            if not file_exists:
                writer.writeheader()

            for alert in alerts:
                # Ensure all columns are present
                row = {col: alert.get(col, '') for col in CSV_COLUMNS}
                writer.writerow(row)

        logger.info(f"✅ Saved {len(alerts)} alerts to {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Error saving alerts to file: {e}")


def main():
    """Main execution flow."""
    logger.info("🔍 Starting Zendesk Watch Agent...")

    # Fetch all tickets
    tickets = fetch_zendesk_tickets()
    if not tickets:
        logger.error("No tickets fetched")
        return

    # Filter for vendor alerts
    vendor_tickets = filter_vendor_alert_tickets(tickets)
    if not vendor_tickets:
        logger.info("No vendor alert tickets found")
        return

    # Load existing alerts to avoid duplicates
    existing_ids = load_existing_alerts()
    logger.info(f"📊 {len(existing_ids)} alerts already processed")

    # Process new tickets
    new_alerts = []
    for ticket in vendor_tickets:
        ticket_id = str(ticket.get('id'))

        # Skip if already processed
        if ticket_id in existing_ids:
            continue

        alert = process_ticket(ticket)
        if alert:
            new_alerts.append(alert)

    # Save new alerts
    save_alerts_to_file(new_alerts)

    # Final summary
    logger.info(
        f"✅ Fetched {len(tickets)} tickets. "
        f"{len(vendor_tickets)} match vendors. "
        f"{len(new_alerts)} new alerts extracted."
    )


if __name__ == "__main__":
    main()
