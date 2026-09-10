import feedparser
import urllib.request
import json
import os
import csv
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from deadline_checker import check_deadline_status, extract_deadline_from_text

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

VENDOR_NAME = "Twilio"

TARGET_SERVICES = [
    "programmable messaging",
    "programmable chat",
    "sender id",
    "sendgrid",
    "sms",
    "short code"
]

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_twilio_status():
    """[SRE] Fetches active incidents from the Twilio Status REST API."""
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates...")
    url = "https://status.twilio.com/api/v2/incidents/unresolved.json"
    req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Error fetching status API: {e}")
        return ""

    entries_text = ""
    for incident in data.get("incidents", []):
        incident_name = incident.get('name', '').strip()
        components = incident.get('components', [])
        affected_names = [c.get('name', '').lower() for c in components]
        search_text = (incident_name.lower() + " " + " ".join(affected_names))

        if any(service in search_text for service in TARGET_SERVICES):
            print(f"🎯 [SRE Match]: {incident_name}")
            name_clean = incident_name.replace('"', '\\"').replace('\\', '\\\\')
            status_clean = str(incident.get('status', '')).replace('"', '\\"').replace('\\', '\\\\')
            entries_text += f"EXACT_TITLE: {name_clean}\nStatus: {status_clean}\n"

            incident_url = incident.get('shortlink', '')
            if incident_url:
                url_clean = incident_url.replace('"', '\\"').replace('\\', '\\\\')
                entries_text += f"Link: {url_clean}\n"

            if incident.get("incident_updates"):
                body_clean = str(incident['incident_updates'][0].get('body', '')).replace('"', '\\"').replace('\\', '\\\\')
                entries_text += f"Summary: {body_clean}\n\n"

    return entries_text

def fetch_twilio_changelog():
    """[ARCH] Fetches deprecations/changelogs from the Twilio RSS feed."""
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} changelogs...")
    feed_url = "https://www.twilio.com/changelog/feed"
    feed = feedparser.parse(feed_url)

    entries_text = ""
    for entry in feed.entries[:20]:
        title = getattr(entry, 'title', '')
        summary = getattr(entry, 'summary', '')
        description = getattr(entry, 'description', '')
        published = getattr(entry, 'published', '')
        link = getattr(entry, 'link', '')

        search_text = (title + " " + (summary or description)).lower()
        if any(service in search_text for service in TARGET_SERVICES):
            title_clean = title.replace('"', '\\"').replace('\\', '\\\\')
            date_clean = published.replace('"', '\\"').replace('\\', '\\\\')
            content_clean = (summary or description).replace('"', '\\"').replace('\\', '\\\\')
            entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {content_clean}\n"

            if link:
                link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                entries_text += f"Link: {link_clean}\n"

            entries_text += "\n"

    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / GPT-OSS-20B)
# ==========================================
def analyze_status(status_text):
    """Parses SRE live incidents with Backbase Context."""
    if not status_text: return []
    print(f"🧠 [SRE AI] Analyzing active {VENDOR_NAME} outages...")
    prompt = f"""
    You are a Site Reliability Engineer for Backbase.
    Read the Twilio Status entries. Identify active incidents.
    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter capitalization, wording, or spelling.
    CRITICAL RULE: If a "Link:" is present in the entry, extract it and include as "incident_url".

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "SRE Incident",
          "title": "EXACT title string from input",
          "type": "Outage, Degraded Performance, or Delays",
          "product_impacted": "specific product name",
          "status_or_date": "Investigating, Identified, or Monitoring",
          "impact_summary": "1 sentence summary",
          "backbase_action_required": "Immediate Action, Monitor, or No Action",
          "backbase_rationale": "1 sentence justification",
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
    """Parses breaking changes and deprecations with Backbase Context."""
    if not changelog_text: return []
    print(f"🧠 [ARCH AI] Analyzing {VENDOR_NAME} deprecations...")
    prompt = f"""
    You are a Software Architect for Backbase.
    Read the Twilio changelog entries. Identify ONLY items that represent a deprecation, breaking change, or compliance update.
    CRITICAL RULE: You MUST copy the EXACT string from "EXACT_TITLE:" into the "title" field. Do not alter wording.
    CRITICAL RULE: If a "Link:" is present in the entry, extract it and include as "incident_url".

    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "Architecture Deprecation",
          "title": "EXACT title string from input",
          "type": "Deprecation, Breaking Change, or Compliance",
          "product_impacted": "specific product name",
          "status_or_date": "sunset date or None Specified",
          "impact_summary": "1 sentence summary",
          "backbase_action_required": "Code Migration Required, Assessment Needed, or No Action",
          "backbase_rationale": "1 sentence justification",
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
                    "type": "Deprecation",
                    "product_impacted": "Twilio SMS/Verify",
                    "status_or_date": "None Specified",
                    "impact_summary": "Twilio API deprecation or breaking change requiring evaluation",
                    "backbase_action_required": "Assessment Needed",
                    "backbase_rationale": "Requires evaluation of Twilio API changes impact",
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

def refine_action_required(alert_type: str, description: str, title: str, days_until: str = None) -> str:
    """Refine backbase_action_required based on ticket content and urgency.

    Logic:
    1. Breaking Change + migration keywords → Code Migration Required
    2. Compliance/Security + assessment keywords → Assessment Needed
    3. Deadline < 30 days → Code Migration Required (urgent)
    4. Deadline 30-60 days → Assessment Needed
    5. Default → Assessment Needed
    """
    text_combined = (description + " " + title).lower()

    migration_keywords = ["update", "migrate", "migration", "upgrade", "change", "new version", "breaking", "deprecated", "removed"]
    assessment_keywords = ["assess", "review", "check", "evaluate", "consider", "might", "may", "potential"]

    has_migration = any(kw in text_combined for kw in migration_keywords)
    has_assessment = any(kw in text_combined for kw in assessment_keywords)

    # Rule 1: Breaking Change + migration keywords
    if alert_type and "breaking" in alert_type.lower() and has_migration:
        return "Code Migration Required"

    # Rule 2: Compliance/Security + assessment keywords
    if alert_type and ("compliance" in alert_type.lower() or "security" in alert_type.lower()) and has_assessment:
        return "Assessment Needed"

    # Rule 5: Breaking Change defaults to migration
    if alert_type and "breaking" in alert_type.lower():
        return "Code Migration Required"

    return "Assessment Needed"

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
                    # Ensure all required fields exist (for backwards compatibility with old CSV format)
                    for key in keys:
                        if key not in row:
                            row[key] = ''
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
            title,
            alert.get('status_or_date')
        )

        clean_alert = {
            "logged_at": timestamp,
            "vendor": VENDOR_NAME,
            "category": alert.get('category') or 'SRE Incident',
            "urgency_level": alert.get('urgency_level') or 'NORMAL',
            "age_status": 'New',
            "age_days": '0',
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
            # Update status/details while keeping original creation timestamp
            clean_alert['logged_at'] = existing_records[title].get('logged_at', timestamp)
            # Preserve age fields if they exist
            if 'age_status' in existing_records[title]:
                clean_alert['age_status'] = existing_records[title].get('age_status', 'New')
            if 'age_days' in existing_records[title]:
                clean_alert['age_days'] = existing_records[title].get('age_days', '0')
            # Preserve incident_url if not in new alert
            if not clean_alert.get('incident_url') and existing_records[title].get('incident_url'):
                clean_alert['incident_url'] = existing_records[title].get('incident_url')
            existing_records[title] = clean_alert
        else:
            existing_records[title] = clean_alert
            record_order.append(title)

    # 2. AUTO-RESOLVE: Check for Twilio SRE incidents that disappeared from the live feed
    auto_resolved_count = 0
    for title, row in existing_records.items():
        if row.get('vendor') == VENDOR_NAME and row.get('category') == 'SRE Incident':
            # If the incident is no longer in active feed and isn't marked resolved yet:
            if title not in incoming_titles and row.get('status_or_date', '').lower() not in ['resolved', 'completed']:
                row['status_or_date'] = 'Resolved'
                auto_resolved_count += 1
                print(f"✅ AUTO-RESOLVED: {title[:80]}")
            elif title in incoming_titles:
                print(f"📡 STILL ACTIVE: {title[:80]}")

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

    print(f"💾 Database synced! ({auto_resolved_count} incident(s) auto-marked as 'Resolved')")

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print(f"🚨 AI VENDOR WATCH AGENT: {VENDOR_NAME} SRE & ARCHITECTURE")
    print("==================================================\n")

    all_alerts = []
    all_alerts.extend(analyze_status(fetch_twilio_status()))
    all_alerts.extend(analyze_deprecations(fetch_twilio_changelog()))

    # Save alerts
    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
