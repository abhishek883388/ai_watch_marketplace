import feedparser
import urllib.request
import json
import os
import csv
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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

VENDOR_NAME = "Yodlee"

# Backbase uses Yodlee for:
# 1. Account Verification
# 2. Transaction Enrichment
TARGET_SERVICES = [
    "account verification",
    "transaction enrichment",
    "account aggregation",
    "verification",
    "enrichment"
]

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_yodlee_status():
    """[SRE] Fetches active incidents from Yodlee's status page.

    Yodlee uses Statuspage.io for status tracking.
    Official page: https://yodlee.statuspage.io/
    Uses JSON API to fetch unresolved incidents only.
    """
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates...")

    entries_text = ""

    try:
        # Use Statuspage.io JSON API to fetch incidents
        api_url = "https://yodlee.statuspage.io/api/v2/incidents.json"
        req = urllib.request.Request(api_url)

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        incidents = data.get("incidents", [])

        # Filter for unresolved incidents matching our services
        for incident in incidents:
            incident_name = incident.get('name', '').strip()
            status = incident.get('status', '').lower()

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

                incident_url = incident.get('shortlink', '') or incident.get('url', '')
                if incident_url:
                    url_clean = incident_url.replace('"', '\\"').replace('\\', '\\\\')
                    entries_text += f"Link: {url_clean}\n"

                if incident.get("incident_updates"):
                    update_body = str(incident['incident_updates'][0].get('body', '')).replace('"', '\\"').replace('\\', '\\\\')
                    entries_text += f"Summary: {update_body}\n"

                entries_text += "\n"

    except Exception as e:
        print(f"⚠️ [SRE API Error] Failed to fetch {VENDOR_NAME} status (check network): {type(e).__name__}")

    if not entries_text:
        print(f"ℹ️ No unresolved {VENDOR_NAME} incidents matching monitored services")

    return entries_text

def fetch_yodlee_changelog():
    """[ARCH] Fetches SDK updates and API changes from Yodlee.

    Yodlee publishes updates through:
    - Envestnet/Yodlee Developer Portal
    - API Release Notes
    - SDK Changelogs (GitHub, npm registry, Maven Central)
    - Support documentation updates

    Captures: API deprecations, breaking changes, SDK upgrades,
    authentication changes, endpoint changes, security updates, data format changes.
    """
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} SDK changelogs...")

    entries_text = ""

    # PRIMARY: Try to fetch from GitHub releases
    github_feeds = [
        ("Yodlee OpenAPI", "https://api.github.com/repos/Yodlee/OpenAPI/releases"),
        ("Yodlee FastLink", "https://api.github.com/repos/Yodlee/fastlink/releases"),
    ]

    for platform, api_url in github_feeds:
        try:
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                releases = json.loads(response.read().decode())

            if releases:
                for release in releases[:5]:
                    title = release.get('name', '') or release.get('tag_name', '')
                    content = release.get('body', '').lower()
                    published_at = release.get('published_at', 'N/A')

                    search_text = (title + " " + content).lower()

                    if any(keyword in search_text for keyword in [
                        "deprecat", "breaking", "removed", "sunset", "vulnerab", "security",
                        "upgrade required", "end of support", "end of life", "eol", "migration",
                        "sdk upgrade", "api change", "api version", "important update"
                    ]):
                        title_clean = f"{platform} - {title}".replace('"', '\\"').replace('\\', '\\\\')
                        body_clean = content[:200].replace('"', '\\"').replace('\\', '\\\\')
                        date_clean = published_at.replace('"', '\\"').replace('\\', '\\\\')

                        entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {body_clean}\n"

                        link = release.get('html_url', '')
                        if link:
                            link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                            entries_text += f"Link: {link_clean}\n"

                        entries_text += "\n"

        except Exception:
            continue

    # FALLBACK: Try RSS feeds from documentation (if available)
    rss_feeds = [
        ("Yodlee Blog", "https://yodlee.com/feed/"),
    ]

    for platform, feed_url in rss_feeds:
        try:
            feed = feedparser.parse(feed_url)

            if feed.entries:
                for entry in feed.entries[:5]:
                    content = entry.get('content', [{'value': ''}])[0].get('value', '') if entry.get('content') else ''
                    summary = entry.get('summary', '')
                    search_text = (entry.title + " " + summary + " " + content).lower()

                    if any(keyword in search_text for keyword in [
                        "deprecat", "breaking", "removed", "sunset", "vulnerab", "security",
                        "upgrade required", "end of support", "end of life", "eol", "migration",
                        "sdk upgrade", "api change", "api version", "important"
                    ]):
                        title_base = entry.title.strip()
                        title_clean = f"Yodlee {platform} - {title_base}".replace('"', '\\"').replace('\\', '\\\\')
                        summary_clean = summary.replace('"', '\\"').replace('\\', '\\\\')
                        date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')

                        entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n"

                        link = entry.get('link', '')
                        if link:
                            link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                            entries_text += f"Link: {link_clean}\n"

                        entries_text += "\n"

        except Exception:
            continue

    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / GPT-OSS-20B)
# ==========================================
def analyze_status(status_text):
    """Parses SRE live incidents with Backbase financial data context."""
    if not status_text:
        return []
    print(f"🧠 [SRE AI] Analyzing active {VENDOR_NAME} outages...")
    prompt = f"""
    You are a Site Reliability Engineer for Backbase (digital banking platform).
    Read the {VENDOR_NAME} incident entries for data aggregation and enrichment services.

    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter capitalization, wording, or spelling.
    CRITICAL RULE: If a "Link:" is present in the entry, extract it and include as "incident_url".

    Focus on:
    1. How does this incident impact Backbase's data aggregation and enrichment services?
    2. Does this affect user account verification or KYC processes?
    3. Are authentication or data retrieval APIs affected?
    4. Is there a security or data integrity risk?

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "SRE Incident",
          "title": "EXACT title string from input",
          "type": "Outage, Degraded Performance, or Delays",
          "product_impacted": "Data Aggregation, Enrichment, or Authentication",
          "status_or_date": "Investigating, Identified, or Monitoring",
          "impact_summary": "1 sentence summary of how data services are impacted",
          "backbase_action_required": "Immediate Action, Monitor, or No Action",
          "backbase_rationale": "1 sentence on data integrity/security implications",
          "incident_url": "URL from Link field if present, else empty string"
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
    """Parses API changes and SDK deprecations with Backbase data context."""
    if not changelog_text:
        return []
    print(f"🧠 [ARCH AI] Analyzing {VENDOR_NAME} deprecations...")
    prompt = f"""
    You are a Software Architect for Backbase (digital banking platform).
    Read the {VENDOR_NAME} changelog entries for data aggregation, enrichment, and authentication APIs.
    Identify ONLY items that represent a deprecation, breaking change, SDK sunset, or security update.

    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter wording.
    CRITICAL RULE: If a "Link:" is present in the entry, extract it and include as "incident_url".

    Focus on:
    1. Will this require code migration in Backbase's data aggregation layer?
    2. Does this affect our KYC verification or user enrichment flows?
    3. Are there security implications for financial data handling?
    4. Do we need to update our API integration code?

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "Architecture Deprecation",
          "title": "EXACT title string from input",
          "type": "Deprecation, Breaking Change, or Security Update",
          "product_impacted": "Data Aggregation, Enrichment, or Authentication API",
          "status_or_date": "sunset date or None Specified",
          "impact_summary": "1 sentence summary of data/api impact",
          "backbase_action_required": "Code Migration Required, Assessment Needed, or No Action",
          "backbase_rationale": "1 sentence on why Backbase does or does not need to act",
          "incident_url": "URL from Link field if present, else empty string"
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
        # Fallback: extract basic alerts from raw changelog text if Groq fails
        print(f"   Generating fallback alerts from {len(changelog_text.split('EXACT_TITLE:'))-1} articles...")
        fallback_alerts = []
        for entry in changelog_text.split('EXACT_TITLE:')[1:]:
            lines = entry.strip().split('\n')
            if lines:
                title = lines[0].strip()
                incident_url = ""
                for line in lines:
                    if line.startswith('Link:'):
                        incident_url = line.replace('Link:', '').strip()
                        break

                fallback_alerts.append({
                    "category": "Architecture Deprecation",
                    "title": title,
                    "type": "API Change",
                    "product_impacted": "Data Aggregation API",
                    "status_or_date": "None Specified",
                    "impact_summary": "Yodlee API or data format update requiring evaluation",
                    "backbase_action_required": "Assessment Needed",
                    "backbase_rationale": "Requires evaluation of Yodlee API changes impact",
                    "incident_url": incident_url
                })
        return fallback_alerts

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

def refine_action_required(alert_type: str, description: str, title: str) -> str:
    """Refine backbase_action_required based on alert content."""
    text_combined = (description + " " + title).lower()
    migration_keywords = ["api change", "breaking", "deprecat", "upgrade", "migration", "update", "required", "new version"]
    has_migration = any(kw in text_combined for kw in migration_keywords)

    if alert_type and ("breaking" in alert_type.lower() or "security" in alert_type.lower()) and has_migration:
        return "Code Migration Required"

    if alert_type and "breaking" in alert_type.lower():
        return "Code Migration Required"

    return "Assessment Needed"

# ==========================================
# 4. CSV DATABASE OPERATIONS
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
        "incident_url",
        "product_impacted",
        "type",
        "status_or_date",
        "impact_summary",
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
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incoming_titles = set()

    # 1. Process active incoming alerts
    for alert in alerts:
        title = (alert.get('title') or 'N/A').strip()
        incoming_titles.add(title)

        # Refine action based on alert content
        refined_action = refine_action_required(
            alert.get('type', ''),
            alert.get('impact_summary', ''),
            title
        )

        clean_alert = {
            "logged_at": timestamp,
            "vendor": VENDOR_NAME,
            "category": alert.get('category') or 'SRE Incident',
            "urgency_level": alert.get('urgency_level') or 'NORMAL',
            "deadline_date": alert.get('deadline_date') or 'N/A',
            "title": title,
            "incident_url": alert.get('incident_url') or '',
            "product_impacted": alert.get('product_impacted') or 'Unspecified',
            "type": alert.get('type') or 'N/A',
            "status_or_date": alert.get('status_or_date') or 'N/A',
            "impact_summary": alert.get('impact_summary') or 'N/A',
            "backbase_action_required": refined_action,
            "backbase_rationale": alert.get('backbase_rationale') or 'AI could not determine rationale.'
        }

        if title in existing_records:
            clean_alert['logged_at'] = existing_records[title].get('logged_at', timestamp)
            clean_alert['age_status'] = existing_records[title].get('age_status', 'New')
            clean_alert['age_days'] = existing_records[title].get('age_days', '0')

        existing_records[title] = clean_alert
        if title not in record_order:
            record_order.append(title)

    # 2. Auto-resolve incidents no longer in active list
    auto_resolved_count = 0
    for title in record_order:
        if title not in incoming_titles and existing_records[title].get('vendor') == VENDOR_NAME:
            if existing_records[title].get('status_or_date', '').lower() not in ['resolved', 'completed']:
                existing_records[title]['status_or_date'] = 'Resolved'
                auto_resolved_count += 1

    # 3. Sort by urgency level
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
    print("\n" + "=" * 50)
    print(f"🚨 AI VENDOR WATCH AGENT: {VENDOR_NAME} SRE & ARCHITECTURE")
    print("=" * 50 + "\n")

    all_alerts = []
    all_alerts.extend(analyze_status(fetch_yodlee_status()))
    all_alerts.extend(analyze_deprecations(fetch_yodlee_changelog()))

    # Save alerts
    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
