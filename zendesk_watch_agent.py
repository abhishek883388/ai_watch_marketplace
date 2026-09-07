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

# Monitored vendors - STRICT filtering for only these vendors
# IMPORTANT: Use specific vendor names and avoid generic keywords like "payment", "security", "compliance"
# Primary match is by tag name, secondary is by text keywords
MONITORED_VENDORS = {
    "twilio": ["twilio", "sendgrid", "sms", "messaging"],
    "entrust": ["entrust", "card", "x-pays", "ssl", "certificate"],
    "entrust_identity": ["onfido", "identity verification"],
    "jumio": ["jumio", "kyc", "identity", "verification"],
    "atomic": ["atomic", "payments"],
    "biocatch": ["biocatch", "fraud"],
    "codat": ["codat", "accounting"],
    "complyadvantage": ["complyadvantage", "aml"],
    "docusign": ["docusign", "esign", "signature"],
    "feedzai": ["feedzai", "risk", "fraud"],
    "jack_henry": ["jack henry", "ensenta", "banking"],
    "middesk": ["middesk", "business verification"],
    "paymentus": ["paymentus"],
    "payveris": ["payveris", "verification"],
    "saleedge": ["saleedge", "sales"],
    "savvy_money": ["savvy money", "financial"],
    "smarty": ["smarty", "address"],
    "yodlee": ["yodlee", "financial", "aggregation"],
}

# Vendor tag names for Zendesk tag matching (maps tag name to vendor key)
VENDOR_TAG_NAMES = set(MONITORED_VENDORS.keys())

# Alert keywords that COUNT (vendor-initiated changes)
VALID_ALERT_KEYWORDS = [
    "deprecation", "deprecated", "breaking change",
    "sunset", "eol", "end of life",
    "security vulnerability", "security patch", "security update",
    "compliance requirement", "regulatory change",
    "api change", "endpoint change", "migration required",
    "upgrade required", "action required"
]

# Alert keywords that DON'T count (internal/operational, not vendor alerts)
FALSE_POSITIVE_KEYWORDS = [
    "security group", "security issue",
    "compliance check",
    "production mode",
    "sandbox", "test", "testing",
    "account missing", "configuration", "setup",
    "password reset", "login issue",
    "network security", "firewall"
]

# Track rejected vendors for logging
rejected_vendors = set()

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
    """Fetch tickets from Zendesk created/updated in the past 3 months using search API."""
    if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
        logger.error("Missing Zendesk credentials in .env file")
        return []

    base_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com"
    headers = get_zendesk_headers()

    # Calculate date 3 months ago
    date_3_months_ago = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    # First, get total ticket count
    total_count = 0
    try:
        count_url = urljoin(base_url, "/api/v2/tickets.json")
        count_response = requests.get(count_url, headers=headers, params={"per_page": 1}, timeout=30)
        count_response.raise_for_status()
        total_count = count_response.json().get('count', 0)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not fetch total ticket count: {e}")

    # Fetch tickets from past 3 months using search API
    all_tickets = []
    search_url = urljoin(base_url, "/api/v2/search.json")

    # Query for tickets created or updated in the past 3 months
    query = f'created_at>={date_3_months_ago} OR updated_at>={date_3_months_ago}'
    params = {
        "query": query,
        "per_page": 100
    }

    try:
        page = 1
        while search_url:
            logger.info(f"Fetching page {page} (3-month filter)...")
            response = requests.get(search_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            tickets = data.get('results', [])
            if not tickets:
                break

            all_tickets.extend(tickets)

            # Get next page URL
            search_url = data.get('next_page')
            page += 1

        queried_count = len(all_tickets)
        if total_count > 0:
            logger.info(f"✅ Queried {queried_count} tickets (past 3 months) out of {total_count} total")
        else:
            logger.info(f"✅ Queried {queried_count} tickets (past 3 months)")

        return all_tickets if all_tickets else []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Zendesk tickets: {e}")
        if all_tickets:
            logger.info(f"Returning {len(all_tickets)} tickets fetched before error")
            return all_tickets
        return []


def get_vendor_from_tags(tags: List[str]) -> Optional[str]:
    """Check if ticket tags contain a monitored vendor tag. Returns vendor name or None."""
    if not tags:
        return None

    tags_lower = [tag.lower() for tag in tags]
    for tag in tags_lower:
        if tag in VENDOR_TAG_NAMES:
            return tag

    return None


def contains_vendor_keyword(text: str) -> Optional[str]:
    """Check if text contains MONITORED vendor keywords with word boundaries. Returns vendor name or None."""
    text_lower = text.lower()
    for vendor, keywords in MONITORED_VENDORS.items():
        for keyword in keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                return vendor
    return None


def contains_false_positive_keyword(text: str) -> Tuple[bool, str]:
    """Check if text contains false positive keywords. Returns (has_false_positive, reason)."""
    text_lower = text.lower()
    for keyword in FALSE_POSITIVE_KEYWORDS:
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            return True, f"contains '{keyword}' (not a vendor alert)"
    return False, ""


def contains_valid_alert_keyword(text: str) -> Tuple[bool, str]:
    """Check if text contains VALID alert keywords (vendor changes).
    Returns (has_alert, keyword_found)."""
    text_lower = text.lower()

    for keyword in VALID_ALERT_KEYWORDS:
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            return True, keyword

    return False, ""


def has_phrase_based_alert(text: str, vendor: str) -> Tuple[bool, str]:
    """Check for phrase-based patterns like 'vendor X deprecation'.
    This is stricter than just finding keywords separately.
    Returns (has_phrase_alert, reason)."""
    text_lower = text.lower()
    vendor_lower = vendor.lower()

    # Patterns: vendor + alert keyword in close proximity
    # e.g., "twilio deprecation", "jumio breaking change", "entrust sunset"
    patterns = [
        rf'{re.escape(vendor_lower)}.*?deprecat',  # Within ~100 chars
        rf'{re.escape(vendor_lower)}.*?breaking change',
        rf'{re.escape(vendor_lower)}.*?sunset',
        rf'{re.escape(vendor_lower)}.*?eol',
        rf'{re.escape(vendor_lower)}.*?end of life',
        rf'{re.escape(vendor_lower)}.*?security (vulnerability|patch|update)',
        rf'{re.escape(vendor_lower)}.*?compliance requirement',
        rf'{re.escape(vendor_lower)}.*?api change',
        rf'{re.escape(vendor_lower)}.*?migration required',
    ]

    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL):
            return True, pattern[:40]

    return False, ""


def detect_any_vendor(text: str) -> Optional[str]:
    """Detect ANY vendor keyword (monitored or not) for tracking rejected vendors with word boundaries."""
    text_lower = text.lower()
    common_vendors = {
        "docusign": ["docusign", "esignature"],
        "codat": ["codat", "accounting", "erp"],
        "atomic": ["atomic", "kyb"],
        "biocatch": ["biocatch", "fraud"],
        "jack henry": ["jack henry", "jha"],
        "bankcard": ["bankcard", "visa", "mastercard"],
    }

    for vendor, keywords in common_vendors.items():
        for keyword in keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                return vendor

    return None


def filter_vendor_alert_tickets(tickets: List[Dict]) -> Tuple[List[Dict], Dict]:
    """Filter tickets with STRICT criteria:
    1. Must have monitored vendor (tag or keyword)
    2. Must NOT contain false positive keywords
    3. Must contain VALID alert keyword
    4. Should have phrase-based match (vendor + alert together)

    Returns (filtered_tickets, stats) with detailed rejection logging."""
    filtered = []
    stats = {
        'monitored_vendor_matches': 0,
        'tag_matches': 0,
        'valid_alert_matches': 0,
        'phrase_alert_matches': 0,
        'false_positives_rejected': 0,
        'no_alert_rejected': 0,
        'rejected_vendors': set()
    }

    rejected_log = []

    for ticket in tickets:
        subject = ticket.get('subject', '')
        description = ticket.get('description', '')
        tags = ticket.get('tags', [])
        ticket_id = ticket.get('id', '')
        combined_text = f"{subject} {description}"

        # Step 1: Check for monitored vendor (PRIMARY: tags, FALLBACK: text)
        monitored_vendor = get_vendor_from_tags(tags)
        if monitored_vendor:
            stats['tag_matches'] += 1
        else:
            monitored_vendor = contains_vendor_keyword(combined_text)

        if not monitored_vendor:
            any_vendor = detect_any_vendor(combined_text)
            if any_vendor:
                stats['rejected_vendors'].add(any_vendor)
            continue

        stats['monitored_vendor_matches'] += 1

        # Step 2: REJECT if contains false positive keywords
        has_false_positive, fp_reason = contains_false_positive_keyword(combined_text)
        if has_false_positive:
            rejected_log.append(f"Ticket #{ticket_id} ({monitored_vendor}): {fp_reason}")
            stats['false_positives_rejected'] += 1
            continue

        # Step 3: Check for VALID alert keywords
        has_valid_alert, alert_keyword = contains_valid_alert_keyword(combined_text)
        if not has_valid_alert:
            rejected_log.append(f"Ticket #{ticket_id} ({monitored_vendor}): no valid alert keyword")
            stats['no_alert_rejected'] += 1
            continue

        stats['valid_alert_matches'] += 1

        # Step 4: Check for phrase-based alert (stricter)
        has_phrase_alert, pattern = has_phrase_based_alert(combined_text, monitored_vendor)
        if has_phrase_alert:
            stats['phrase_alert_matches'] += 1

        # INCLUDE: All criteria met
        ticket['detected_vendor'] = monitored_vendor
        filtered.append(ticket)
        logger.debug(f"✅ Included: #{ticket_id} ({monitored_vendor}) - {alert_keyword}")

    # Log rejected tickets
    if rejected_log:
        logger.info(f"⚠️  Rejected tickets ({len(rejected_log)}):")
        for log_entry in rejected_log[:10]:  # Show first 10
            logger.info(f"  {log_entry}")
        if len(rejected_log) > 10:
            logger.info(f"  ... and {len(rejected_log) - 10} more")

    stats['rejected_vendors'] = sorted(list(stats['rejected_vendors']))

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

    # Fetch tickets from past 3 months
    tickets = fetch_zendesk_tickets()
    if not tickets:
        logger.warning("⚠️  No tickets found in the past 3 months")
        return

    # Filter for monitored vendor alerts with strict filtering
    vendor_tickets, filter_stats = filter_vendor_alert_tickets(tickets)

    # Log filtering statistics
    monitored_count = filter_stats['monitored_vendor_matches']
    tag_matches = filter_stats['tag_matches']
    valid_alert_count = filter_stats['valid_alert_matches']
    phrase_alert_count = filter_stats['phrase_alert_matches']
    false_positive_rejected = filter_stats['false_positives_rejected']
    no_alert_rejected = filter_stats['no_alert_rejected']
    rejected = filter_stats['rejected_vendors']

    logger.info(
        f"📊 Filtering: {len(tickets)} tickets → {monitored_count} vendor matches "
        f"({tag_matches} via tags) → {valid_alert_count} with valid alerts "
        f"({phrase_alert_count} phrase-matched) → {len(vendor_tickets)} final alerts"
    )
    logger.info(
        f"⚠️  Rejected: {false_positive_rejected} false positives + {no_alert_rejected} no alert = "
        f"{false_positive_rejected + no_alert_rejected} tickets"
    )

    if vendor_tickets:
        if rejected:
            logger.info(f"📌 Non-monitored vendors found: {', '.join(rejected)}")
    else:
        logger.info("ℹ️  No vendor alert tickets found (all rejected or no matches)")
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
        f"✅ Processing complete: {len(vendor_tickets)} monitored vendor alerts. "
        f"{len(new_alerts)} new alerts extracted."
    )


if __name__ == "__main__":
    main()
