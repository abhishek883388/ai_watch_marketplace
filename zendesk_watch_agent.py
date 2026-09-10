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

# Monitored vendor names - simple list for keyword matching
MONITORED_VENDORS = [
    "twilio", "sendgrid",
    "entrust", "onfido",
    "jumio",
    "atomic",
    "biocatch",
    "codat",
    "complyadvantage",
    "docusign",
    "feedzai",
    "jack henry", "ensenta",
    "middesk",
    "paymentus",
    "payveris",
    "saleedge",
    "savvy money",
    "smarty",
    "yodlee",
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
    """Fetch ALL tickets from Zendesk (no time filter) using search API."""
    if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
        logger.error("Missing Zendesk credentials in .env file")
        return []

    base_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com"
    headers = get_zendesk_headers()

    # First, get total ticket count
    total_count = 0
    try:
        count_url = urljoin(base_url, "/api/v2/tickets.json")
        count_response = requests.get(count_url, headers=headers, params={"per_page": 1}, timeout=30)
        count_response.raise_for_status()
        total_count = count_response.json().get('count', 0)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch total ticket count: {e}")

    # Fetch ALL tickets using list endpoint (no date filter - capture complete marketplace history)
    all_tickets = []
    tickets_url = urljoin(base_url, "/api/v2/tickets.json")

    try:
        page = 1
        url = tickets_url
        while url:
            logger.info(f"Fetching page {page}...")
            response = requests.get(url, headers=headers, params={"per_page": 100}, timeout=30)
            response.raise_for_status()

            data = response.json()
            tickets = data.get('tickets', [])
            if not tickets:
                break

            all_tickets.extend(tickets)

            # Get next page URL
            url = data.get('next_page')
            page += 1

        queried_count = len(all_tickets)
        if total_count > 0:
            logger.info(f"✅ Queried {queried_count} tickets out of {total_count} total")
        else:
            logger.info(f"✅ Queried {queried_count} tickets")

        return all_tickets if all_tickets else []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Zendesk tickets: {e}")
        if all_tickets:
            logger.info(f"Returning {len(all_tickets)} tickets fetched before error")
            return all_tickets
        return []


def find_vendor_in_text(text: str) -> Optional[str]:
    """Check if text contains any monitored vendor name (case-insensitive).
    Returns vendor name if found, None otherwise."""
    text_lower = text.lower()
    for vendor in MONITORED_VENDORS:
        if vendor in text_lower:
            return vendor
    return None


def filter_vendor_alert_tickets(tickets: List[Dict]) -> Tuple[List[Dict], Dict]:
    """Filter: include ALL tickets that mention any monitored vendor by name.
    Comprehensive marketplace tracking - captures all vendor-related issues regardless of type.
    Returns (filtered_tickets, stats)."""
    filtered = []
    vendor_counts = {}

    for ticket in tickets:
        subject = ticket.get('subject', '')
        description = ticket.get('description', '')
        combined_text = f"{subject} {description}"

        # Check if ticket mentions any monitored vendor
        vendor = find_vendor_in_text(combined_text)

        if vendor:
            ticket['detected_vendor'] = vendor
            filtered.append(ticket)
            vendor_counts[vendor] = vendor_counts.get(vendor, 0) + 1

    # Build vendor summary for logging
    vendor_summary = " | ".join(f"{v}: {count}" for v, count in sorted(vendor_counts.items()))

    stats = {
        'vendor_counts': vendor_counts,
        'vendor_summary': vendor_summary
    }

    return filtered, stats


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
        'vendor': parsed['vendor'].capitalize(),
        'product': parsed['vendor'].capitalize(),
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


def load_existing_alerts() -> Dict[str, Dict]:
    """Load existing alerts from CSV as a dict keyed by ticket_id."""
    if not os.path.exists(OUTPUT_FILE):
        return {}

    existing_alerts = {}
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticket_id = str(row.get('ticket_id', ''))
                if ticket_id:
                    existing_alerts[ticket_id] = row
    except Exception as e:
        logger.warning(f"Error reading existing alerts: {e}")

    return existing_alerts


def save_alerts_to_file(alerts: List[Dict]) -> None:
    """Save alerts to CSV file (rewrite mode - preserves older tickets outside query window)."""
    if not alerts:
        logger.info("No alerts to save")
        return

    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
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

    # Fetch tickets from past 3 months
    tickets = fetch_zendesk_tickets()
    if not tickets:
        logger.warning("⚠️  No tickets found in the past 3 months")
        return

    # Filter for monitored vendors (simple: just check if vendor name is mentioned)
    vendor_tickets, filter_stats = filter_vendor_alert_tickets(tickets)

    # Log results
    vendor_summary = filter_stats['vendor_summary']
    logger.info(
        f"✅ Extracted {len(vendor_tickets)} tickets containing monitored vendor names"
    )
    if vendor_summary:
        logger.info(f"Breakdown: {vendor_summary}")

    if not vendor_tickets:
        logger.info("ℹ️  No tickets found mentioning monitored vendors")
        return

    # Load existing alerts (dict keyed by ticket_id)
    existing_alerts = load_existing_alerts()
    logger.info(f"📊 {len(existing_alerts)} alerts already in CSV")

    # Process tickets and merge with existing alerts
    updated_alerts = {}
    new_count = 0
    updated_count = 0

    for ticket in vendor_tickets:
        ticket_id = str(ticket.get('id'))
        alert = process_ticket(ticket)

        if alert:
            if ticket_id in existing_alerts:
                updated_count += 1
            else:
                new_count += 1
            updated_alerts[ticket_id] = alert

    # Preserve existing alerts not in current query (older tickets outside 3-month window)
    for ticket_id, alert in existing_alerts.items():
        if ticket_id not in updated_alerts:
            updated_alerts[ticket_id] = alert

    # Convert dict to list and save
    all_alerts = list(updated_alerts.values())
    save_alerts_to_file(all_alerts)

    # Final summary
    logger.info(
        f"✅ Processing complete: {len(vendor_tickets)} monitored vendor alerts. "
        f"{new_count} new, {updated_count} updated. Total in CSV: {len(all_alerts)}"
    )


if __name__ == "__main__":
    main()
