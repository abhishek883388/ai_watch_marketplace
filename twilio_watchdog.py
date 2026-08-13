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
    api_key=os.environ.get("GROQ_API_KEY")  # Pulls securely from GitHub Secrets or local environment
)

# Services filter to target specific alerts and reduce noise
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
    url = "https://status.twilio.com/api/v2/incidents/unresolved.json"
    
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
    """Parses SRE live incidents with Groq."""
    if not status_text:
        return []
        
    print("🧠 [SRE AI] Analyzing active outages with Groq...")
    prompt = f"""
    Read the Twilio Status entries. Identify active incidents, outages, or delays.
    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "SRE Incident",
          "title": "incident title",
          "type": "Outage, Degraded Performance, or Delays",
          "product_impacted": "specific product name",
          "status_or_date": "Investigating, Identified, or Monitoring",
          "impact_summary": "1 sentence summary"
        }}
      ]
    }}
    If no active issues exist, return {{"alerts": []}}.
    Entries:
    {status_text}
    """
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return parse_ai_json(response.choices[0].message.content)

def analyze_deprecations(changelog_text):
    """Parses breaking changes and deprecations with Groq."""
    if not changelog_text:
        return []
        
    print("🧠 [ARCH AI] Analyzing deprecations with Groq...")
    prompt = f"""
    Read the Twilio changelog entries. Identify ONLY items that represent a deprecation, breaking change, sunset API, or compliance update.
    Output strictly as JSON:
    {{
      "alerts": [
        {{
          "category": "Architecture Deprecation",
          "title": "title of change",
          "type": "Deprecation, Breaking Change, or Compliance",
          "product_impacted": "specific product name",
          "status_or_date": "sunset date or None Specified",
          "impact_summary": "1 sentence summary"
        }}
      ]
    }}
    If none exist, return {{"alerts": []}}.
    Entries:
    {changelog_text}
    """
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return parse_ai_json(response.choices[0].message.content)

def parse_ai_json(raw_json):
    """Safely extracts the alerts array from LLM JSON response."""
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict):
            return data.get('alerts') or data.get('items') or []
        elif isinstance(data, list):
            return data
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
    return []

# ==========================================
# 4. STORAGE (JSON & CSV REPOSITORY DATABASE)
# ==========================================
# ==========================================
# 4. STORAGE (JSON & CSV REPOSITORY DATABASE)
# ==========================================
def save_alerts_to_file(alerts):
    """Appends new alerts to JSON and always ensures CSV is updated."""
    json_filename = "watchdog_alerts.json"
    csv_filename = "watchdog_alerts.csv"
    
    # 1. Load existing JSON data
    try:
        with open(json_filename, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
        
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing_titles = {item.get('title') for item in data if isinstance(item, dict)}
    
    added_count = 0
    for alert in alerts:
        if alert.get('title') not in existing_titles:
            alert['logged_at'] = timestamp
            data.append(alert)
            added_count += 1
        
    # Save JSON database
    with open(json_filename, 'w') as f:
        json.dump(data, f, indent=4)
        
    # 2. ALWAYS generate/update CSV (even if empty or no new additions)
    keys = ["logged_at", "category", "title", "product_impacted", "type", "status_or_date", "impact_summary"]
    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        if data:
            writer.writerows(data)

    print(f"💾 Database updated! Added {added_count} new alert(s). JSON & CSV synced.")
# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print("🚨 AI VENDOR WATCHDOG: TWILIO SRE & ARCHITECTURE")
    print("==================================================\n")
    
    all_alerts = []
    
    # 1. Fetch & Analyze Live SRE Incidents
    status_text = fetch_twilio_status()
    sre_alerts = analyze_status(status_text)
    all_alerts.extend(sre_alerts)
    
    # 2. Fetch & Analyze Architecture Deprecations
    changelog_text = fetch_twilio_changelog()
    arch_alerts = analyze_deprecations(changelog_text)
    all_alerts.extend(arch_alerts)
    
    # 3. Store Results locally
    if not all_alerts:
        print("\n✅ All operational! No live incidents or upcoming deprecations found.")
    else:
        print(f"\n🚨 FOUND {len(all_alerts)} MATCHING ITEM(S):\n")
        save_alerts_to_file(all_alerts)
        
    print("\n✅ Script execution complete. Exiting clean.")

if __name__ == "__main__":
    main()
