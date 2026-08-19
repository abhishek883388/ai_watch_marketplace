import feedparser
import urllib.request
import json
import os
import csv
from datetime import datetime
from openai import OpenAI

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
            entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n\n"

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

                entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n\n"

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
3. Respond ONLY with a valid JSON object matching this structure:

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
      "backbase_rationale": "One sentence explaining impact on customer onboarding."
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
          "backbase_rationale": "1 sentence explaining why Backbase does or does not need to act on the SDK or API."
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

# ==========================================
# 4. STORAGE (CSV WITH AUTO-RESOLUTION)
# ==========================================
def save_alerts_to_file(alerts):
    """Updates existing alerts, auto-resolves vanished SRE incidents, or appends new ones."""
    csv_filename = "watchdog_alerts.csv"
    keys = [
        "logged_at", 
        "vendor",
        "category", 
        "title", 
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
            "title": title,
            "product_impacted": alert.get('product_impacted') or 'Unspecified',
            "type": alert.get('type') or 'N/A',
            "status_or_date": alert.get('status_or_date') or 'N/A',
            "impact_summary": alert.get('impact_summary') or 'N/A',
            "backbase_action_required": alert.get('backbase_action_required') or 'Assessment Needed',
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

    # 3. Write updated database back to CSV
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for title in record_order:
            writer.writerow(existing_records[title])

    os.chmod(csv_filename, 0o600)

    print(f"💾 Database synced! ({auto_resolved_count} {VENDOR_NAME} incident(s) auto-marked as 'Resolved')")

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print(f"🚨 AI VENDOR WATCHDOG: {VENDOR_NAME} SRE & ARCHITECTURE")
    print("==================================================\n")
    
    all_alerts = []
    all_alerts.extend(analyze_status(fetch_jumio_status()))
    all_alerts.extend(analyze_deprecations(fetch_jumio_changelog()))
    
    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
