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

VENDOR_NAME = "Entrust"

TARGET_SERVICES = [
    "push card",
    "x-pays",
    "apple pay",
    "google pay",
    "secure card display",
    "card number",
    "cvv",
    "pin"
]

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_entrust_status():
    """[SRE] Fetches active incidents from Entrust's DCS status page.

    Entrust uses Statuspage.io for status tracking.
    Official page: https://entrust-dcs.statuspage.io/
    """
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates...")

    # Entrust DCS (Digital Certificate Services) Statuspage.io feeds
    status_feeds = [
        "https://entrust-dcs.statuspage.io/history.rss",      # Primary RSS feed
        "https://entrust-dcs.statuspage.io/api/v2/incidents.json",  # JSON API
    ]

    entries_text = ""
    feed_found = False

    for feed_url in status_feeds:
        try:
            if feed_url.endswith(".rss"):
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    feed_found = True
                    for entry in feed.entries[:15]:
                        search_text = (entry.title + " " + entry.get('summary', '')).lower()

                        if any(service in search_text for service in TARGET_SERVICES):
                            title_clean = entry.title.strip().replace('"', '\\"').replace('\\', '\\\\')
                            summary_clean = entry.get('summary', 'N/A').replace('"', '\\"').replace('\\', '\\\\')
                            date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')
                            print(f"🎯 [SRE Match]: {entry.title.strip()}")
                            entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n\n"
                    break

            elif feed_url.endswith(".com") or feed_url.endswith(".io"):
                req = urllib.request.Request(feed_url)
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        content = response.read().decode()
                        if ".rss" in content or "rss" in content.lower():
                            print(f"ℹ️ Found RSS feed reference in {feed_url}, add .rss endpoint")
                except Exception:
                    continue

        except Exception:
            continue

    if not feed_found:
        print(f"⚠️ Could not reach {VENDOR_NAME} status feeds. Check:")
        print(f"   - https://entrust-dcs.statuspage.io/ (main status page)")
        print(f"   - RSS feed: https://entrust-dcs.statuspage.io/history.rss")
        print(f"   - API: https://entrust-dcs.statuspage.io/api/v2/incidents.json")

    return entries_text

def fetch_entrust_changelog():
    """[ARCH] Fetches SDK updates and deprecations from Entrust documentation.

    Entrust publishes updates through:
    - GitHub repositories: github.com/Entrust/[sdk-repo]/releases.atom
    - Developer portal: https://docs.entrust.com or https://developer.entrust.com
    - Product announcements and release notes
    """
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} SDK changelogs...")

    changelog_feeds = [
        ("Mobile SDK", "https://github.com/Entrust/mobile-sdk/releases.atom"),
        ("Push Card SDK", "https://github.com/Entrust/pushcard-sdk/releases.atom"),
        ("Digital Banking APIs", "https://github.com/Entrust/digital-banking-apis/releases.atom"),
    ]

    entries_text = ""
    feeds_attempted = 0

    for platform, feed_url in changelog_feeds:
        try:
            feed = feedparser.parse(feed_url)

            if feed.entries:
                feeds_attempted += 1
                for entry in feed.entries[:5]:
                    content = entry.get('content', [{'value': ''}])[0].get('value', '') if entry.get('content') else ''
                    summary = entry.get('summary', '')
                    search_text = (entry.title + " " + summary + " " + content).lower()

                    if any(keyword in search_text for keyword in ["sdk", "deprecation", "breaking", "removed", "sunset", "vulnerability", "security", "card", "x-pays", "payment"]):
                        title_base = entry.title.strip()
                        title_clean = f"Entrust {platform} - {title_base}".replace('"', '\\"').replace('\\', '\\\\')
                        summary_clean = summary.replace('"', '\\"').replace('\\', '\\\\')
                        date_clean = entry.get('published', 'N/A').replace('"', '\\"').replace('\\', '\\\\')

                        entries_text += f"EXACT_TITLE: {title_clean}\nDate: {date_clean}\nSummary: {summary_clean}\n\n"

        except Exception:
            continue

    if feeds_attempted == 0:
        print(f"⚠️ Could not fetch {VENDOR_NAME} changelog data. Verify URLs:")
        print(f"   - GitHub repos: https://github.com/Entrust/[repo-name]/releases.atom")
        print(f"   - Developer portal: https://developer.entrust.com")
        print(f"   - Official docs: https://www.entrust.com/documentation")

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

# ==========================================
# 4. STORAGE (CSV WITH AUTO-RESOLUTION)
# ==========================================
def save_alerts_to_file(alerts):
    """Updates existing alerts, auto-resolves vanished SRE incidents, or appends new ones."""
    csv_filename = "entrust_alerts.csv"
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

    # 2. AUTO-RESOLVE: Check for Entrust SRE incidents that disappeared from active feed
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
    all_alerts.extend(analyze_status(fetch_entrust_status()))
    all_alerts.extend(analyze_deprecations(fetch_entrust_changelog()))

    save_alerts_to_file(all_alerts)
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
