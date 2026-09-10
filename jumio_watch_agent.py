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

VENDOR_NAME = "Jumio"

TARGET_SERVICES = [
    "identity verification",
    "id&v",
    "identity verification web",
    "identity verification sdk",
    "identity verification processing",
    "identity verification callback",
    "identity verification retrieval api",
    "performnetverify api",
    "doc proof",
    "liveness"
]

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_jumio_status():
    """[SRE] Fetches active incidents from Jumio's official monitor feed."""
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates...")
    feed_url = "https://monitor.jumio.com/history.rss"
    feed = feedparser.parse(feed_url)

    entries_text = ""
    for entry in feed.entries[:15]:
        search_text = (entry.title + " " + entry.get('summary', '')).lower()

        if any(service in search_text for service in TARGET_SERVICES) or "identity verification" in search_text:
            title_clean = entry.title.strip().replace('"', '\\"').replace('\\', '\\\\')
            summary_clean = entry.get('summary', 'N/A').replace('"', '\\"').replace('\\', '\\\\')
            date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')
            print(f"🎯 [{VENDOR_NAME} SRE Match]: {entry.title.strip()}")
            entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n"

            link = entry.get('link', '')
            if link:
                link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                entries_text += f"Link: {link_clean}\n"

            entries_text += "\n"

    return entries_text
    
def fetch_jumio_changelog():
    """[ARCH] Fetches SDK updates and deprecations from Jumio GitHub Releases."""
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} SDK changelogs from GitHub...")

    github_feeds = [
        ("Android SDK", "https://github.com/Jumio/mobile-sdk-android/releases.atom"),
        ("iOS SDK", "https://github.com/Jumio/mobile-sdk-ios/releases.atom")
    ]

    entries_text = ""
    for platform, feed_url in github_feeds:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:5]:
            content = entry.get('content', [{'value': ''}])[0].get('value', '')
            summary = entry.get('summary', '')
            search_text = (entry.title + " " + summary + " " + content).lower()

            if any(keyword in search_text for keyword in ["sdk", "deprecation", "breaking", "removed", "sunset", "vulnerability"]):
                raw_version = entry.title.replace('v', '').strip()
                title_clean = f"Jumio {platform} v{raw_version}".replace('"', '\\"').replace('\\', '\\\\')
                summary_clean = summary.replace('"', '\\"').replace('\\', '\\\\')
                date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')

                entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n"

                link = entry.get('link', '')
                if link:
                    link_clean = link.replace('"', '\\"').replace('\\', '\\\\')
                    entries_text += f"Link: {link_clean}\n"

                entries_text += "\n"

    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / GPT-OSS-20B)
# ==========================================

def analyze_status(status_text):
    """Parses SRE live incidents with Backbase ID&V Context."""
    if not status_text: 
        return []
        
    print(f"🧠 [SRE AI] Analyzing active {VENDOR_NAME} outages...")
    
    prompt = f"""You are a Site Reliability Engineer for Backbase (digital banking platform).
Analyze the following Jumio incident entries for Identity Verification (ID&V).

Rules:
1. Extract active incidents.
2. For the "title" field, you MUST copy the EXACT string from "EXACT_TITLE:" without changing spelling or casing.
3. If a "Link:" is present in the entry, extract it and include as "incident_url".
4. Respond ONLY with a valid JSON object matching this structure:

{{
  "alerts": [
    {{
      "category": "SRE Incident",
      "title": "EXACT title string from input",
      "type": "Outage, Degraded Performance, or Delays",
      "product_impacted": "Identity Verification",
      "status_or_date": "Investigating",
      "impact_summary": "One sentence summary of outage.",
      "backbase_action_required": "Monitor",
      "backbase_rationale": "One sentence explaining impact on customer onboarding.",
      "incident_url": "URL from Link field if present, else empty string"
    }}
  ]
}}

If no active issues exist, return: {{"alerts": []}}

Entries to analyze:
{status_text}"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return parse_ai_json(response.choices[0].message.content)
    except RuntimeError as e:
        raise
    except Exception as e:
        print(f"⚠️ [SRE AI Error] Failed to analyze incidents (check GROQ_API_KEY and network)")
        return []

def analyze_deprecations(changelog_text):
    """Parses breaking changes and SDK deprecations with Backbase Context."""
    if not changelog_text: return []
    print(f"🧠 [ARCH AI] Analyzing {VENDOR_NAME} deprecations...")
    prompt = f"""
    You are a Software Architect for Backbase (a digital banking platform).
    Read the {VENDOR_NAME} changelog entries for ID&V. Identify ONLY items that represent a deprecation, breaking change, SDK sunset, or compliance update.
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
          "backbase_rationale": "1 sentence explaining why Backbase does or does not need to act on the SDK or API.",
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
                    "type": "Breaking Change",
                    "product_impacted": "Jumio SDK",
                    "status_or_date": "None Specified",
                    "impact_summary": "Jumio SDK update or breaking change requiring evaluation",
                    "backbase_action_required": "Assessment Needed",
                    "backbase_rationale": "Requires evaluation of Jumio SDK changes impact",
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
    migration_keywords = ["update", "migrate", "migration", "upgrade", "change", "new version", "breaking", "deprecated", "removed", "required"]
    has_migration = any(kw in text_combined for kw in migration_keywords)

    if alert_type and ("breaking" in alert_type.lower() or "deprecat" in alert_type.lower()) and has_migration:
        return "Code Migration Required"

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
            existing_records[title] = clean_alert
        else:
            existing_records[title] = clean_alert
            record_order.append(title)

    # 2. AUTO-RESOLVE: Check for Jumio SRE incidents that disappeared from active feed
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
    all_alerts.extend(analyze_status(fetch_jumio_status()))
    all_alerts.extend(analyze_deprecations(fetch_jumio_changelog()))

    # Save alerts
    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
