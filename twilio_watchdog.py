import feedparser
import urllib.request
import json
import ssl
import os
from datetime import datetime
from openai import OpenAI

# ==========================================
# 1. CONFIGURATION & CREDENTIALS
# ==========================================
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key="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" 
)

# Optional: Add your Slack Webhook URL. Leave empty string "" to skip Slack.
SLACK_WEBHOOK_URL = "" 

# Monitored services filter (Prevents alert fatigue)
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
# 3. AI ANALYZERS
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
# 4. STORAGE & INTEGRATIONS
# ==========================================
def save_alerts_to_file(alerts):
    """Saves all alerts to a local JSON file for Streamlit."""
    filename = "watchdog_alerts.json"
    
    # Reload existing file to append
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
        
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for alert in alerts:
        alert['logged_at'] = timestamp
        data.append(alert)
        
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)
        
    print(f"💾 Saved {len(alerts)} alert(s) to watchdog_alerts.json!")

def send_slack_alert(alerts):
    """Sends combined alerts to Slack."""
    if not SLACK_WEBHOOK_URL or not alerts:
        return
        
    message = "🚨 *AI VENDOR WATCHDOG: TWILIO UPDATE*\n\n"
    for alert in alerts:
        emoji = "🔴" if alert.get('category') == "SRE Incident" else "⚠️"
        message += f"{emoji} *[{alert.get('category', 'ALERT').upper()}]* {alert.get('title')}\n"
        message += f"📦 *Product:* {alert.get('product_impacted')}\n"
        message += f"📊 *Status/Date:* {alert.get('status_or_date')}\n"
        message += f"📝 *Impact:* {alert.get('impact_summary')}\n\n"
        
    payload = {"text": message}
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                print("✅ Successfully routed alerts to Slack!")
    except Exception as e:
        print(f"❌ Slack Error: {e}")

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print("🚨 AI VENDOR WATCHDOG: TWILIO SRE & ARCHITECTURE")
    print("==================================================\n")
    
    all_alerts = []
    
    # 1. Check Live SRE Incidents
    status_text = fetch_twilio_status()
    sre_alerts = analyze_status(status_text)
    all_alerts.extend(sre_alerts)
    
    # 2. Check Architecture Deprecations
    changelog_text = fetch_twilio_changelog()
    arch_alerts = analyze_deprecations(changelog_text)
    all_alerts.extend(arch_alerts)
    
    # 3. Handle Results
    if not all_alerts:
        print("\n✅ All operational! No live incidents or upcoming deprecations found.")
    else:
        print(f"\n🚨 FOUND {len(all_alerts)} TOTAL ALERT(S):\n")
        for alert in all_alerts:
            print(f"[{alert.get('category')}] {alert.get('title')}")
            print(f"📦 Product: {alert.get('product_impacted')}")
            print(f"🗓️ Status/Date: {alert.get('status_or_date')}")
            print(f"📝 Impact: {alert.get('impact_summary')}\n")
            
        save_alerts_to_file(all_alerts)
        send_slack_alert(all_alerts)

if __name__ == "__main__":
    main()
