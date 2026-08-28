#!/usr/bin/env python3
"""
Zendesk Weekly Marketplace Report Generator
Generates weekly statistics on vendor tickets from Zendesk.
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
import pandas as pd
from jinja2 import Template

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

# Monitored vendors - same as zendesk_watch_agent.py
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

REPORT_FILE = "zendesk_weekly_report.csv"
REPORT_HTML_FILE = "zendesk_weekly_report.html"


def get_zendesk_headers() -> Dict[str, str]:
    """Create Zendesk API headers with Basic Auth."""
    auth_string = f"{ZENDESK_EMAIL}/token:{ZENDESK_API_TOKEN}"
    auth_bytes = auth_string.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

    return {
        'Authorization': f'Basic {auth_b64}',
        'Content-Type': 'application/json'
    }


def detect_vendor(text: str, tags: List[str]) -> Optional[str]:
    """Detect vendor from text or tags. Returns vendor name or None."""
    if not text:
        return None

    # Check tags first
    tags_lower = [tag.lower() for tag in tags]
    for vendor_name in MONITORED_VENDORS.keys():
        if vendor_name in tags_lower:
            return vendor_name

    # Fall back to text matching
    text_lower = text.lower()
    for vendor_name, keywords in MONITORED_VENDORS.items():
        for keyword in keywords:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                return vendor_name

    return None


def fetch_all_zendesk_tickets() -> List[Dict]:
    """Fetch ALL tickets from Zendesk (no date filter for weekly report)."""
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


def get_weekly_stats() -> Dict[str, Dict]:
    """
    Query Zendesk tickets and calculate weekly statistics by vendor.
    Returns dict with vendor stats: total, open, closed, avg_age, oldest_age.
    """
    tickets = fetch_all_zendesk_tickets()
    if not tickets:
        logger.warning("No tickets fetched from Zendesk")
        return {}

    # Group tickets by vendor
    vendor_tickets = {}
    undetected_tickets = []

    for ticket in tickets:
        subject = ticket.get('subject', '')
        description = ticket.get('description', '')
        tags = ticket.get('tags', [])
        combined_text = f"{subject} {description}"

        vendor = detect_vendor(combined_text, tags)

        if vendor:
            if vendor not in vendor_tickets:
                vendor_tickets[vendor] = []
            vendor_tickets[vendor].append(ticket)
        else:
            undetected_tickets.append(ticket)

    # Calculate statistics for each vendor
    stats = {}
    now = datetime.now(datetime.now().astimezone().tzinfo)

    for vendor_name, vendor_list in vendor_tickets.items():
        total = len(vendor_list)
        open_count = sum(1 for t in vendor_list if t.get('status') == 'open')
        closed_count = sum(1 for t in vendor_list if t.get('status') == 'closed')

        # Calculate ages
        ages_days = []
        for ticket in vendor_list:
            try:
                created = datetime.fromisoformat(ticket.get('created_at', '').replace('Z', '+00:00'))
                age = (now - created).days
                ages_days.append(age)
            except:
                pass

        avg_age = sum(ages_days) / len(ages_days) if ages_days else 0
        oldest_age = max(ages_days) if ages_days else 0

        stats[vendor_name] = {
            'total_tickets': total,
            'open_tickets': open_count,
            'closed_tickets': closed_count,
            'avg_age_days': round(avg_age, 1),
            'oldest_ticket_days': oldest_age,
        }

    logger.info(f"📊 Grouped {len(tickets)} tickets into {len(vendor_tickets)} vendors")
    logger.info(f"⚠️  {len(undetected_tickets)} tickets could not be classified")

    return stats


def generate_html_report(stats: Dict[str, Dict]) -> str:
    """Generate HTML report from statistics."""
    template_str = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Zendesk Weekly Marketplace Report</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
            h1 { color: #333; border-bottom: 3px solid #0066cc; padding-bottom: 10px; }
            table { border-collapse: collapse; width: 100%; background-color: white; margin-top: 20px; }
            th { background-color: #0066cc; color: white; padding: 12px; text-align: left; }
            td { padding: 10px; border-bottom: 1px solid #ddd; }
            tr:hover { background-color: #f9f9f9; }
            .summary { background-color: #e3f2fd; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
            .metric { display: inline-block; margin-right: 30px; }
            .metric-value { font-size: 24px; font-weight: bold; color: #0066cc; }
            .metric-label { color: #666; font-size: 12px; }
            .timestamp { color: #999; font-size: 12px; margin-top: 20px; }
        </style>
    </head>
    <body>
        <h1>📊 Zendesk Weekly Marketplace Report</h1>

        <div class="summary">
            <div class="metric">
                <div class="metric-value">{{ total_vendors }}</div>
                <div class="metric-label">MONITORED VENDORS</div>
            </div>
            <div class="metric">
                <div class="metric-value">{{ total_tickets }}</div>
                <div class="metric-label">TOTAL TICKETS</div>
            </div>
            <div class="metric">
                <div class="metric-value">{{ total_open }}</div>
                <div class="metric-label">OPEN TICKETS</div>
            </div>
            <div class="metric">
                <div class="metric-value">{{ total_closed }}</div>
                <div class="metric-label">CLOSED TICKETS</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Vendor</th>
                    <th>Total Tickets</th>
                    <th>Open</th>
                    <th>Closed</th>
                    <th>Avg Age (days)</th>
                    <th>Oldest (days)</th>
                </tr>
            </thead>
            <tbody>
                {% for vendor, data in vendors %}
                <tr>
                    <td><strong>{{ vendor }}</strong></td>
                    <td>{{ data.total_tickets }}</td>
                    <td>{{ data.open_tickets }}</td>
                    <td>{{ data.closed_tickets }}</td>
                    <td>{{ data.avg_age_days }}</td>
                    <td>{{ data.oldest_ticket_days }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="timestamp">Generated: {{ timestamp }}</div>
    </body>
    </html>
    """

    template = Template(template_str)

    total_tickets = sum(s['total_tickets'] for s in stats.values())
    total_open = sum(s['open_tickets'] for s in stats.values())
    total_closed = sum(s['closed_tickets'] for s in stats.values())

    html = template.render(
        vendors=sorted(stats.items()),
        total_vendors=len(stats),
        total_tickets=total_tickets,
        total_open=total_open,
        total_closed=total_closed,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

    return html


def save_csv_report(stats: Dict[str, Dict]) -> None:
    """Save statistics to CSV file."""
    if not stats:
        logger.info("No statistics to save")
        return

    try:
        with open(REPORT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Vendor',
                'Total Tickets',
                'Open Tickets',
                'Closed Tickets',
                'Avg Age (days)',
                'Oldest Ticket (days)',
                'Generated'
            ])

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for vendor, data in sorted(stats.items()):
                writer.writerow([
                    vendor,
                    data['total_tickets'],
                    data['open_tickets'],
                    data['closed_tickets'],
                    data['avg_age_days'],
                    data['oldest_ticket_days'],
                    timestamp
                ])

        logger.info(f"✅ Saved report to {REPORT_FILE}")
    except Exception as e:
        logger.error(f"Error saving CSV report: {e}")


def save_html_report(html: str) -> None:
    """Save HTML report to file."""
    try:
        with open(REPORT_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"✅ Saved HTML report to {REPORT_HTML_FILE}")
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")


def print_console_report(stats: Dict[str, Dict]) -> None:
    """Print statistics to console in table format."""
    if not stats:
        logger.info("No statistics to display")
        return

    logger.info("\n" + "=" * 100)
    logger.info("ZENDESK WEEKLY MARKETPLACE REPORT")
    logger.info("=" * 100)

    total_tickets = sum(s['total_tickets'] for s in stats.values())
    total_open = sum(s['open_tickets'] for s in stats.values())
    total_closed = sum(s['closed_tickets'] for s in stats.values())

    logger.info(f"Total Vendors: {len(stats)} | Total Tickets: {total_tickets} | Open: {total_open} | Closed: {total_closed}")
    logger.info("=" * 100)

    # Create pandas DataFrame for nice display
    data = []
    for vendor, stats_data in sorted(stats.items()):
        data.append({
            'Vendor': vendor,
            'Total': stats_data['total_tickets'],
            'Open': stats_data['open_tickets'],
            'Closed': stats_data['closed_tickets'],
            'Avg Age': stats_data['avg_age_days'],
            'Oldest': stats_data['oldest_ticket_days'],
        })

    df = pd.DataFrame(data)
    logger.info("\n" + df.to_string(index=False))
    logger.info("\n" + "=" * 100 + "\n")


def main():
    """Main execution flow."""
    logger.info("🔍 Starting Zendesk Weekly Report Generator...")

    # Get statistics
    stats = get_weekly_stats()

    if not stats:
        logger.warning("No statistics generated")
        return

    # Save reports
    save_csv_report(stats)
    html_report = generate_html_report(stats)
    save_html_report(html_report)

    # Print to console
    print_console_report(stats)

    logger.info("✅ Weekly report generation complete!")


if __name__ == "__main__":
    main()
