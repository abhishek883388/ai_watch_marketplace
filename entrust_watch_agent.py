import feedparser
import urllib.request
import json
import os
import csv
import re
from datetime import datetime
from openai import OpenAI
from deadline_checker import check_deadline_status, extract_deadline_from_text

# ==========================================
# 1. CONFIGURATION & CREDENTIALS
# ==========================================
groq_api_key = os.environ.get("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("GROQ_API_KEY environment variable is required but not set. Please set it before running this script.")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=groq_api_key
)

VENDOR_NAME = "Entrust"

TARGET_SERVICES = [
    "digital card",
    "mobile sdk",
    "card solution",
    "issuer tsp",
    "apple pay",
    "google pay",
    "push notification",
    "wallet"
]

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_entrust_status():
    """[SRE] Fetches active incidents from Entrust's DCS status page.

    Entrust uses Statuspage.io for status tracking.
    Official page: https://entrust-dcs.statuspage.io/
    Uses JSON API to fetch unresolved incidents only.
    """
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates...")

    entries_text = ""

    try:
        # Use Statuspage.io JSON API to fetch incidents
        api_url = "https://entrust-dcs.statuspage.io/api/v2/incidents.json"
        req = urllib.request.Request(api_url)

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        incidents = data.get("incidents", [])

        # Filter for unresolved incidents matching our services
        for incident in incidents:
            incident_name = incident.get('name', '').strip()
            status = incident.get('status', '').lower()
            incident_url = incident.get('shortlink', '')

            # Only include unresolved incidents
            if status in ['resolved', 'completed', 'postmortem']:
                continue

            components = incident.get('components', [])
            affected_names = [c.get('name', '').lower() for c in components]
            search_text = (incident_name.lower() + " " + " ".join(affected_names))

            if any(service in search_text for service in TARGET_SERVICES):
                print(f"🎯 [SRE Match]: {incident_name}")
                name_clean = incident_name.replace('"', '\\"').replace('\\', '\\\\')
                status_clean = status.replace('"', '\\"').replace('\\', '\\\\')
                entries_text += f"EXACT_TITLE: {name_clean}\nStatus: {status_clean}\n"

                if incident_url:
                    url_clean = incident_url.replace('"', '\\"').replace('\\', '\\\\')
                    entries_text += f"Link: {url_clean}\n"

                if incident.get("incident_updates"):
                    update_body = str(incident['incident_updates'][0].get('body', '')).replace('"', '\\"').replace('\\', '\\\\')
                    entries_text += f"Summary: {update_body}\n\n"

    except Exception as e:
        print(f"⚠️ [SRE API Error] Failed to fetch {VENDOR_NAME} status (check network): {type(e).__name__}")

    if not entries_text:
        print(f"ℹ️ No unresolved {VENDOR_NAME} incidents matching monitored services")

    return entries_text

def fetch_entrust_changelog():
    """[ARCH] Fetches SDK updates and deprecations from Entrust/Antelop support portal.

    Entrust publishes deprecations and breaking changes through:
    - Antelop Support Portal (Freshdesk): https://antelop-support.freshdesk.com/
      * Important FAQs about SDK upgrades and expiry dates
      * Security announcements (TLS certificate renewals, vulnerabilities)
      * Breaking changes and API deprecations
      * End-of-support notices
    - Official Entrust documentation
    - Release notes and announcements

    Captures: SDK upgrades, expiry dates, certificate renewals, deprecations,
    breaking changes, end-of-life announcements, security updates, API changes.
    """
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} SDK changelogs from Antelop support portal...")

    entries_text = ""

    # PRIMARY: Scrape Antelop support portal for deprecations and FAQs
    entries_text += fetch_antelop_articles()

    # FALLBACK: Try RSS feeds (in case Entrust enables them in future)
    changelog_feeds = [
        ("Entrust Developer Docs", "https://docs.entrust.com/feed.xml"),
        ("Entrust Blog", "https://www.entrust.com/blog/feed/"),
    ]

    feeds_found = 0
    for platform, feed_url in changelog_feeds:
        try:
            feed = feedparser.parse(feed_url)

            if feed.entries:
                feeds_found += 1
                for entry in feed.entries[:5]:
                    content = entry.get('content', [{'value': ''}])[0].get('value', '') if entry.get('content') else ''
                    summary = entry.get('summary', '')
                    search_text = (entry.title + " " + summary + " " + content).lower()

                    if any(keyword in search_text for keyword in [
                        "deprecat", "breaking", "removed", "sunset", "vulnerab", "security",
                        "upgrade required", "end of support", "end of life", "eol", "migration",
                        "sdk upgrade", "expiry date", "expire", "important faq"
                    ]):
                        title_base = entry.title.strip()
                        title_clean = f"Entrust {platform} - {title_base}".replace('"', '\\"').replace('\\', '\\\\')
                        summary_clean = summary.replace('"', '\\"').replace('\\', '\\\\')
                        date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')
                        link = entry.get('link', '')

                        entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\n"
                        if link:
                            link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                            entries_text += f"Link: {link_clean}\n"
                        entries_text += f"Summary: {summary_clean}\n\n"

        except Exception:
            continue

    if feeds_found == 0:
        print(f"✓ Scraped {len(entries_text.split('EXACT_TITLE:')) - 1} relevant articles from Antelop support portal")

    return entries_text

def fetch_antelop_articles():
    """[ARCH] Scrapes Antelop support portal (Entrust) for deprecations and important FAQs.

    Antelop is Entrust's Freshdesk support portal. This scraper extracts articles about:
    - SDK upgrades and expiry dates
    - TLS/SSL certificate changes and renewals
    - Breaking changes and deprecations
    - Important FAQs and security notices
    """
    print(f"📡 [ARCH] Scraping Antelop support portal for {VENDOR_NAME} deprecations...")

    entries_text = ""
    antelop_folder_url = "https://antelop-support.freshdesk.com/en/support/solutions/folders/44001203376"

    try:
        req = urllib.request.Request(
            antelop_folder_url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')

        # Extract articles using regex pattern for Freshdesk article links
        articles = re.findall(r'/en/support/solutions/articles/(\d+)-([^"\'<]+)', html)

        if not articles:
            print(f"   ⚠️ No articles found in Antelop folder")
            return entries_text

        print(f"   ✅ Found {len(articles)} articles in Antelop portal")

        # Keywords to filter for deprecations and important updates
        search_keywords = [
            "deprecat", "breaking", "removed", "sunset", "vulnerab", "security",
            "upgrade required", "end of support", "end of life", "eol", "migration",
            "sdk upgrade", "expiry date", "expire", "important faq", "certificate",
            "tls", "ssl", "renewal", "breaking change", "api change"
        ]

        for article_id, slug in articles:
            # Convert slug to readable title
            article_title = slug.replace('-', ' ').strip()
            search_text = article_title.lower()

            # Check if matches our search keywords
            if any(keyword in search_text for keyword in search_keywords):
                print(f"   🎯 [{article_id}] {article_title[:70]}")

                title_clean = article_title.replace('"', '\\"').replace('\\', '\\\\')
                url_clean = f"https://antelop-support.freshdesk.com/en/support/solutions/articles/{article_id}-{slug}".replace('"', '\\"')

                entries_text += f"EXACT_TITLE: {title_clean}\nArticle ID: {article_id}\nURL: {url_clean}\n\n"

    except urllib.error.URLError as e:
        print(f"   ⚠️ Failed to reach Antelop portal: {type(e).__name__}")
    except Exception as e:
        print(f"   ⚠️ Error scraping Antelop: {type(e).__name__}")

    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / GPT-OSS-20B)
# ==========================================
def analyze_status(status_text):
    """Parses SRE live incidents with Backbase payment card context."""
    if not status_text:
        return []
    print(f"🧠 [SRE AI] Analyzing active {VENDOR_NAME} outages...")
    prompt = f"""
    You are a Site Reliability Engineer for Backbase (digital banking platform).
    Read the {VENDOR_NAME} incident entries for Push Card X-Pays and Secure Card Display.

    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter capitalization, wording, or spelling.

    Focus on:
    1. How does this incident impact Backbase's Apple/Google Pay integration?
    2. Does this affect secure card display (number, CVV, expiry, PIN)?
    3. Are payment processing or card handling APIs affected?
    4. Is there a security risk to cardholder data?

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "SRE Incident",
          "title": "EXACT title string from input",
          "type": "Outage, Degraded Performance, or Delays",
          "product_impacted": "Push Card X-Pays or Secure Card Display",
          "status_or_date": "Investigating, Identified, or Monitoring",
          "impact_summary": "1 sentence summary of how payment card features are impacted",
          "incident_url": "URL from input",
          "backbase_action_required": "Immediate Action, Monitor, or No Action",
          "backbase_rationale": "1 sentence on payment/card security implications"
        }}
      ]
    }}
    If no active issues exist, return {{"alerts": []}}. Entries:\n{status_text}
    """
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return parse_ai_json(response.choices[0].message.content)
    except RuntimeError as e:
        raise
    except Exception as e:
        print(f"⚠️ [SRE AI Error] Failed to analyze incidents (check GROQ_API_KEY and network)")
        return []

def analyze_deprecations(changelog_text):
    """Parses breaking changes and SDK deprecations with Backbase payment context."""
    if not changelog_text:
        return []
    print(f"🧠 [ARCH AI] Analyzing {VENDOR_NAME} deprecations...")
    prompt = f"""
    You are a Software Architect for Backbase (digital banking platform).
    Read the {VENDOR_NAME} changelog entries for payment card features.
    Identify ONLY items that represent a deprecation, breaking change, SDK sunset, or security update.

    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter wording.

    Focus on:
    1. Will this require code migration in Backbase's payment processing?
    2. Does this affect our Apple/Google Pay integration?
    3. Are there security implications for card data handling?
    4. Do we need to update our secure card display implementation?

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "Architecture Deprecation",
          "title": "EXACT title string from input",
          "type": "Deprecation, Breaking Change, or Security Update",
          "product_impacted": "Push Card X-Pays, Secure Card Display, or Payment API",
          "status_or_date": "sunset date or None Specified",
          "impact_summary": "1 sentence summary of card/payment impact",
          "incident_url": "URL from input",
          "backbase_action_required": "Code Migration Required, Assessment Needed, or No Action",
          "backbase_rationale": "1 sentence on why Backbase does or does not need to act on payment card features"
        }}
      ]
    }}
    If none exist, return {{"alerts": []}}. Entries:\n{changelog_text}
    """
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return parse_ai_json(response.choices[0].message.content)
    except RuntimeError as e:
        raise
    except Exception as e:
        print(f"⚠️ [ARCH AI Error] Failed to analyze deprecations (check GROQ_API_KEY and network)")
        return []

def parse_ai_json(raw_json):
    """Safely extracts the alerts array from LLM JSON response."""
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict):
            alerts = data.get('alerts') or data.get('items') or []
            if not isinstance(alerts, list):
                raise ValueError(f"Expected 'alerts' to be a list, got {type(alerts).__name__}")
            return alerts
        elif isinstance(data, list):
            return data
        else:
            raise ValueError(f"Expected JSON object or array, got {type(data).__name__}")
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"Failed to parse LLM response: {e}\nRaw content: {raw_json[:200]}")

def enrich_alerts_with_urgency(alerts):
    """Add urgency_level and deadline_date fields to alerts based on status_or_date.

    Args:
        alerts: List of alert dictionaries from AI analysis

    Returns:
        List of enriched alerts with urgency information
    """
    for alert in alerts:
        status_str = alert.get('status_or_date', '')
        impact_str = alert.get('impact_summary', '')

        # Try to extract deadline from status and impact summary
        deadline_info = check_deadline_status(status_str)
        impact_deadlines = extract_deadline_from_text(impact_str)

        # If we found a deadline, use it
        if deadline_info.get('deadline_date'):
            alert['deadline_date'] = deadline_info['deadline_date']
            alert['urgency_level'] = deadline_info['urgency_level']

            # Update action_required based on urgency
            if deadline_info['urgency_level'] == 'OVERDUE':
                alert['backbase_action_required'] = 'OVERDUE - Action Required'
            elif deadline_info['urgency_level'] == 'CRITICAL':
                alert['backbase_action_required'] = 'CRITICAL - Immediate Action'

            # Log urgent items
            if deadline_info['urgency_level'] in ['OVERDUE', 'CRITICAL']:
                print(f"⚠️  {deadline_info['urgency_level']} ITEM: {alert.get('title')} - {deadline_info['message']}")
        elif impact_deadlines:
            # Check first extracted deadline
            first_deadline = impact_deadlines[0][1]
            deadline_info = check_deadline_status(first_deadline)
            if deadline_info.get('deadline_date'):
                alert['deadline_date'] = deadline_info['deadline_date']
                alert['urgency_level'] = deadline_info['urgency_level']
        else:
            alert['deadline_date'] = None
            alert['urgency_level'] = 'NORMAL'

    return alerts

def escalate_alerts_by_age(existing_records):
    """Check Architecture items and escalate urgency/action based on days since reported.

    Status progression:
    - 0-7 days: "New" (NORMAL urgency)
    - 8-14 days: "Aging" (WARNING urgency)
    - 15-30 days: "Pending" (CRITICAL urgency)
    - 30+ days: "Overdue" (OVERDUE urgency, immediate action)
    """
    now = datetime.now()

    for title, row in existing_records.items():
        if row.get('category') == 'Architecture Deprecation':
            try:
                logged_at_str = row.get('logged_at', '')
                logged_at = datetime.strptime(logged_at_str, "%Y-%m-%d %H:%M:%S")
                days_elapsed = (now - logged_at).days
                row['age_days'] = days_elapsed

                # Set age status and escalate urgency/action
                if days_elapsed <= 7:
                    row['age_status'] = 'New'
                    if row.get('urgency_level') == 'NORMAL':
                        row['backbase_action_required'] = 'Assessment Needed'
                elif days_elapsed <= 14:
                    row['age_status'] = 'Aging'
                    row['urgency_level'] = 'WARNING'
                    row['backbase_action_required'] = 'Code Migration Required'
                    print(f"⚠️  AGING (8-14 days): {title}")
                elif days_elapsed <= 30:
                    row['age_status'] = 'Pending'
                    row['urgency_level'] = 'CRITICAL'
                    row['backbase_action_required'] = 'CRITICAL - Immediate Action'
                    print(f"⚠️  CRITICAL (15-30 days): {title}")
                else:
                    row['age_status'] = 'Overdue'
                    row['urgency_level'] = 'OVERDUE'
                    row['backbase_action_required'] = 'OVERDUE - Action Required'
                    print(f"🚨 OVERDUE (30+ days): {title}")
            except (ValueError, TypeError):
                row['age_days'] = 'N/A'
                row['age_status'] = 'Unknown'


# ==========================================
# 4. STORAGE (CSV WITH AUTO-RESOLUTION)
# ==========================================
def save_alerts_to_file(alerts):
    """Updates existing alerts, auto-resolves vanished SRE incidents, or appends new ones."""
    csv_filename = "watch_agent_alerts.csv"
    keys = [
        "logged_at",
        "vendor",
        "category",
        "urgency_level",
        "age_status",
        "age_days",
        "deadline_date",
        "title",
        "product_impacted",
        "type",
        "status_or_date",
        "impact_summary",
        "incident_url",
        "backbase_action_required",
        "backbase_rationale"
    ]

    existing_records = {}
    record_order = []

    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get('title')
                if title:
                    existing_records[title] = row
                    record_order.append(title)

    # Escalate Architecture items based on age since reported
    escalate_alerts_by_age(existing_records)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incoming_titles = set()

    # 1. Process active incoming alerts
    for alert in alerts:
        title = (alert.get('title') or 'N/A').strip()
        incoming_titles.add(title)

        clean_alert = {
            "logged_at": timestamp,
            "vendor": VENDOR_NAME,
            "category": alert.get('category') or 'SRE Incident',
            "urgency_level": alert.get('urgency_level') or 'NORMAL',
            "age_status": 'New',
            "age_days": '0',
            "deadline_date": alert.get('deadline_date') or 'N/A',
            "title": title,
            "product_impacted": alert.get('product_impacted') or 'Unspecified',
            "type": alert.get('type') or 'N/A',
            "status_or_date": alert.get('status_or_date') or 'N/A',
            "impact_summary": alert.get('impact_summary') or 'N/A',
            "incident_url": alert.get('incident_url') or '',
            "backbase_action_required": alert.get('backbase_action_required') or 'Assessment Needed',
            "backbase_rationale": alert.get('backbase_rationale') or 'AI could not determine rationale.'
        }

        if title in existing_records:
            clean_alert['logged_at'] = existing_records[title].get('logged_at', timestamp)
            if 'age_status' in existing_records[title]:
                clean_alert['age_status'] = existing_records[title].get('age_status', 'New')
            if 'age_days' in existing_records[title]:
                clean_alert['age_days'] = existing_records[title].get('age_days', '0')
            existing_records[title] = clean_alert
        else:
            existing_records[title] = clean_alert
            record_order.append(title)

    # 2. AUTO-RESOLVE: Check for Entrust SRE incidents that disappeared from active feed
    auto_resolved_count = 0
    for title, row in existing_records.items():
        if row.get('vendor') == VENDOR_NAME and row.get('category') == 'SRE Incident':
            if title not in incoming_titles and row.get('status_or_date', '').lower() not in ['resolved', 'completed']:
                row['status_or_date'] = 'Resolved'
                auto_resolved_count += 1

    # 3. Sort by urgency level (OVERDUE, CRITICAL, WARNING, NORMAL)
    urgency_order = {'OVERDUE': 0, 'CRITICAL': 1, 'WARNING': 2, 'NORMAL': 3}
    sorted_titles = sorted(
        record_order,
        key=lambda t: (urgency_order.get(existing_records[t].get('urgency_level', 'NORMAL'), 4), t)
    )

    # 4. Write updated database back to CSV
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for title in sorted_titles:
            writer.writerow(existing_records[title])

    os.chmod(csv_filename, 0o600)

    print(f"💾 Database synced! ({auto_resolved_count} {VENDOR_NAME} incident(s) auto-marked as 'Resolved')")

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print(f"🚨 AI VENDOR WATCH AGENT: {VENDOR_NAME} SRE & ARCHITECTURE")
    print("==================================================\n")

    all_alerts = []
    all_alerts.extend(analyze_status(fetch_entrust_status()))
    all_alerts.extend(analyze_deprecations(fetch_entrust_changelog()))

    # Enrich alerts with urgency/deadline information
    all_alerts = enrich_alerts_with_urgency(all_alerts)

    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
