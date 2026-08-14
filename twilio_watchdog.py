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
    print("📡 [SRE] Fetching live Twilio status updates...")
    url = "https://status.twilio.com/api/v2/incidents.json"
    context = ssl._create_unverified_context()
    req = urllib.request.Request(url)
    
    try:
        with urllib.request.urlopen(req, context=context) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Error fetching status API: {e}")
        return ""
        
    entries_text = ""
    for incident in data.get("incidents", []):
        incident_name = incident.get('name', '')
        components = incident.get('components', [])
        affected_names = [c.get('name', '').lower() for c in components]
        search_text = (incident_name.lower() + " " + " ".join(affected_names))
        
        if any(service in search_text for service in TARGET_SERVICES):
            print(f"🎯 [SRE Match]: {incident_name}")
            entries_text += f"Title: {incident_name}\nStatus: {incident.get('status')}\n"
            if incident.get("incident_updates"):
                entries_text += f"Summary: {incident['incident_updates'][0].get('body')}\n\n"
            
    return entries_text

def fetch_twilio_changelog():
    """[ARCH] Fetches deprecations/changelogs from the Twilio RSS feed."""
    print("📡 [ARCH] Fetching latest Twilio changelogs...")
    feed_url = "https://www.twilio.com/changelog/feed"
    feed = feedparser.parse(feed_url)
    
    entries_text = ""
    for entry in feed.entries[:20]: 
        search_text = (entry.title + " " + entry.summary).lower()
        if any(service in search_text for service in TARGET_SERVICES):
            entries_text += f"Title: {entry.title}\nDate: {entry.published}\nSummary: {entry.summary}\n\n"
            
    return entries_text

# ==========================================
# 3. AI ANALYZERS (Groq / Llama 3)
# ==========================================
def analyze_status(status_text):
    if not status_text: return []
    print("🧠 [SRE AI] Analyzing active outages with Backbase context...")
    prompt = f"""
    You are a Site Reliability Engineer for Backbase (a digital banking platform). 
    Read the Twilio Status entries. Identify active incidents.
    Evaluate if this incident requires internal action, communication, or failover routing for Backbase.
    Output strictly as JSON: 
    {{
      "alerts": [
        {{
          "category": "SRE Incident", 
          "title": "incident title", 
          "type": "Outage, Degraded Performance, or Delays", 
          "product_impacted": "specific product name", 
          "status_or_date": "Investigating, Identified, or Monitoring", 
          "impact_summary": "1 sentence summary",
          "backbase_action_required": "Immediate Action, Monitor, or No Action",
          "backbase_rationale": "1 sentence explaining why Backbase does or does not need to act"
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
    if not changelog_text: return []
    print("🧠 [ARCH AI] Analyzing deprecations with Backbase context...")
    prompt = f"""
    You are a Software Architect for Backbase (a digital banking platform). 
    Read the Twilio changelog entries. Identify ONLY items that represent a deprecation, breaking change, or compliance update.
    Evaluate if Backbase needs to update their codebase or migrate APIs.
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
          "backbase_rationale": "1 sentence explaining why Backbase does or does not need to act"
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
    
    # 1. Load existing records into a dictionary keyed by alert 'title'
    existing_records = {}
    record_order = []  # Preserves historical CSV row order
    
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
    
    # 2. Process incoming alerts
    for alert in alerts:
        # DATA SANITATION: Fallbacks for missing/null values
        title = alert.get('title') or 'N/A'
        clean_alert = {
            "logged_at": timestamp,
            "vendor": "Twilio",
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
            # Check if relevant status or impact fields changed
            prev_status = existing_records[title].get('status_or_date')
            new_status = clean_alert['status_or_date']
            
            if prev_status != new_status:
                # Retain original logged_at timestamp, update status and analysis
                clean_alert['logged_at'] = existing_records[title].get('logged_at', timestamp)
                existing_records[title] = clean_alert
                updated_count += 1
        else:
            # New incident discovered: add to records and order tracking
            existing_records[title] = clean_alert
            record_order.append(title)
            added_count += 1

    # 3. Overwrite CSV with updated master list
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
    print("🚨 AI VENDOR WATCHDOG: TWILIO SRE & ARCHITECTURE")
    print("==================================================\n")
    
    all_alerts = []
    all_alerts.extend(analyze_status(fetch_twilio_status()))
    all_alerts.extend(analyze_deprecations(fetch_twilio_changelog()))
    
    # ALWAYS RUN STORAGE (Generates/updates the CSV!)
    save_alerts_to_file(all_alerts)
    
    if not all_alerts:
        print("\n✅ All operational! No live incidents or upcoming deprecations found.")
    else:
        print(f"\n🚨 FOUND {len(all_alerts)} MATCHING ITEM(S):")
        
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
