import feedparser
import urllib.request
import json
import ssl
import os
import csv
from datetime import datetime
from openai import OpenAI

# ==========================================
# 1. CONFIGURATION & CREDENTIALS
# ==========================================
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY") 
)

VENDOR_NAME = "Jumio"

# Filtering strictly for Jumio ID&V (Identity Verification) components
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
    """[SRE] Fetches active and recent incidents from Jumio's official monitor RSS feed."""
    print(f"📡 [SRE] Fetching live {VENDOR_NAME} status updates from monitor.jumio.com...")
    feed_url = "https://monitor.jumio.com/history.rss"
    feed = feedparser.parse(feed_url)
    
    entries_text = ""
    # Look through the most recent entries on the status history feed
    for entry in feed.entries[:15]: 
        search_text = (entry.title + " " + entry.get('summary', '')).lower()
        
        # Match if it contains ID&V target services or broad identity verification terms
        if any(service in search_text for service in TARGET_SERVICES) or "identity verification" in search_text:
            print(f"🎯 [{VENDOR_NAME} SRE Match]: {entry.title}")
            entries_text += f"Title: {entry.title}\nDate: {entry.get('published', 'N/A')}\nSummary: {entry.get('summary', 'N/A')}\n\n"
            
    return entries_text

def fetch_jumio_changelog():
    """[ARCH] Uses the monitor history feed to track SDK updates and deprecations."""
    print(f"📡 [ARCH] Fetching latest {VENDOR_NAME} changelogs & SDK deprecations...")
    # Reuses the robust history feed to catch SDK version updates or maintenance notes
    feed_url = "https://monitor.jumio.com/history.rss"
    feed = feedparser.parse(feed_url)
    
    entries_text = ""
    for entry in feed.entries[:20]: 
        search_text = (entry.title + " " + entry.get('summary', '')).lower()
        
        # Filter specifically for architectural changes, SDK updates, or deprecations
        if any(keyword in search_text for keyword in ["sdk", "deprecation", "breaking", "version", "sunset", "maintenance"]):
            if any(service in search_text for service in TARGET_SERVICES) or "identity verification" in search_text:
                entries_text += f"Title: {entry.title}\nDate: {entry.get('published', 'N/A')}\nSummary: {entry.get('summary', 'N/A')}\n\n"
            
    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / Llama 3)
# ==========================================
def analyze_status(status_text):
    """Parses SRE live incidents with Backbase ID&V Context."""
    if not status_text: return []
    print(f"🧠 [SRE AI] Analyzing {VENDOR_NAME} active outages with Backbase context...")
    prompt = f"""
    You are a Site Reliability Engineer for Backbase (a digital banking platform). 
    Read the {VENDOR_NAME} Status entries regarding Identity Verification (ID&V). Identify active incidents.
    Evaluate if this incident requires internal action, communication, or failover routing for Backbase onboarding flows.
    Output strictly as JSON: 
    {{
      "alerts": [
        {{
          "category": "SRE Incident", 
          "title": "incident title", 
          "type": "Outage, Degraded Performance, or Delays", 
          "product_impacted": "specific product name", 
          "status_or_date": "Investigating, Identified, Monitoring, or Resolved", 
          "impact_summary": "1 sentence summary",
          "backbase_action_required": "Immediate Action, Monitor, or No Action",
          "backbase_rationale": "1 sentence explaining why Backbase does or does not need to act regarding customer onboarding."
        }}
      ]
    }}
    If no active issues exist, return {{"alerts": []}}. Entries:\n{status_text}
    """
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
    )
    return parse_ai_json(response.choices[0].message.content)

def analyze_deprecations(changelog_text):
    """Parses breaking changes and SDK deprecations with Backbase Context."""
    if not changelog_text: return []
    print(f"🧠 [ARCH AI] Analyzing {VENDOR_NAME} deprecations with Backbase context...")
    prompt = f"""
    You are a Software Architect for Backbase (a digital banking platform). 
    Read the {VENDOR_NAME} changelog entries for ID&V. Identify ONLY items that represent a deprecation, breaking change, SDK sunset, or compliance update.
    Evaluate if Backbase needs to update their Mobile SDKs (iOS/Android) or API integrations.
    Output strictly as JSON: 
    {{
      "alerts": [
        {{
          "category": "Architecture Deprecation", 
          "title": "title of change", 
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
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
    )
    return parse_ai_json(response.choices[0].message.content)

def parse_ai_json(raw_json):
    """Safely extracts the alerts array from LLM JSON response."""
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict): return data.get('alerts') or data.get('items') or []
        elif isinstance(data, list): return data
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
    return []

# ==========================================
# 4. STORAGE (CSV UPDATE & APPEND ENGINE)
# ==========================================
def save_alerts_to_file(alerts):
    """Updates existing alerts in CSV if status/details change, or appends new ones."""
    csv_filename = "watchdog_alerts.csv"
    
    # NEW SCHEMA: Note the addition of the "vendor" column
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
    updated_count = 0
    added_count = 0
    
    for alert in alerts:
        title = alert.get('title') or 'N/A'
        clean_alert = {
            "logged_at": timestamp,
            "vendor": VENDOR_NAME,  # Injects "Jumio" into the database
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
            prev_status = existing_records[title].get('status_or_date')
            new_status = clean_alert['status_or_date']
            
            if prev_status != new_status:
                clean_alert['logged_at'] = existing_records[title].get('logged_at', timestamp)
                existing_records[title] = clean_alert
                updated_count += 1
        else:
            existing_records[title] = clean_alert
            record_order.append(title)
            added_count += 1

    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for title in record_order:
            writer.writerow(existing_records[title])

    print(f"💾 Database synced! Added {added_count} new alert(s), updated {updated_count} existing record(s).")

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
    
    if not all_alerts:
        print("\n✅ All operational! No live incidents or upcoming deprecations found.")
    else:
        print(f"\n🚨 FOUND {len(all_alerts)} MATCHING ITEM(S):")
        
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
