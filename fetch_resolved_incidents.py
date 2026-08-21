import feedparser
import urllib.request
import json
import os
import csv
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re

# ==========================================
# 1. CONFIGURATION
# ==========================================
VENDOR_CONFIGS = {
    "Twilio": {
        "target_services": [
            "programmable messaging",
            "programmable chat",
            "sender id",
            "sendgrid",
            "sms",
            "short code"
        ]
    },
    "Jumio": {
        "target_services": [
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
    },
    "Entrust": {
        "target_services": [
            "digital card",
            "mobile sdk",
            "card solution",
            "issuer tsp",
            "apple pay",
            "google pay",
            "push notification"
        ]
    }
}

# ==========================================
# 2. DATA FETCHERS
# ==========================================
def fetch_twilio_resolved():
    """Fetches resolved incidents from Twilio Status API (past 60 days)."""
    print("📡 [Twilio] Fetching resolved incidents...")
    url = "https://status.twilio.com/api/v2/incidents.json"
    req = urllib.request.Request(url)

    incidents = []
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Error fetching Twilio API: {e}")
        return incidents

    sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    target_services = VENDOR_CONFIGS["Twilio"]["target_services"]

    for incident in data.get("incidents", []):
        status = incident.get('status', '')
        if status != 'resolved':
            continue

        # Parse resolved date
        resolved_at_str = incident.get("resolved_at", "")
        if not resolved_at_str:
            continue

        try:
            resolved_at = datetime.fromisoformat(resolved_at_str.replace("Z", "+00:00"))
        except:
            continue

        # Filter for past 60 days
        if resolved_at < sixty_days_ago:
            continue

        # Filter by target services
        incident_name = incident.get('name', '').strip()
        components = incident.get('components', [])
        affected_names = [c.get('name', '').lower() for c in components]
        search_text = (incident_name.lower() + " " + " ".join(affected_names))

        if not any(service in search_text for service in target_services):
            continue

        # Parse created date
        created_at_str = incident.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except:
            created_at = resolved_at

        duration_hours = round((resolved_at - created_at).total_seconds() / 3600, 2)

        # Extract impact summary
        impact_summary = "N/A"
        if incident.get("incident_updates"):
            impact_summary = incident['incident_updates'][0].get('body', 'N/A')[:200]

        incidents.append({
            "vendor": "Twilio",
            "title": incident_name,
            "affected_services": ", ".join([c.get('name', '') for c in components]),
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": resolved_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_hours": duration_hours,
            "status": incident.get('status', ''),
            "impact_summary": impact_summary,
            "incident_type": "Outage"
        })

    print(f"✅ Found {len(incidents)} resolved Twilio incidents")
    return incidents

def fetch_jumio_resolved():
    """Fetches resolved incidents from Jumio Monitor RSS (past 60 days)."""
    print("📡 [Jumio] Fetching resolved incidents...")
    feed_url = "https://monitor.jumio.com/history.rss"
    feed = feedparser.parse(feed_url)

    incidents = []
    target_services = VENDOR_CONFIGS["Jumio"]["target_services"]
    sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)

    for entry in feed.entries[:100]:  # Check more entries
        # Parse date
        try:
            published_str = entry.get('published', '')
            published_dt = parsedate_to_datetime(published_str)
            # Make timezone-aware if needed
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)
        except:
            continue

        if published_dt < sixty_days_ago:
            continue

        title = entry.title.strip()
        summary = entry.get('summary', '').strip()
        search_text = (title + " " + summary).lower()

        # Check if resolved (look for keywords)
        is_resolved = any(keyword in title.lower() for keyword in ["resolved", "completed", "investigated"])
        if not is_resolved:
            continue

        # Filter by target services
        if not any(service in search_text for service in target_services):
            continue

        incidents.append({
            "vendor": "Jumio",
            "title": title,
            "affected_services": "Identity Verification",
            "created_at": "N/A",
            "resolved_at": published_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_hours": "N/A",
            "status": "Resolved",
            "impact_summary": summary[:200],
            "incident_type": "Incident"
        })

    print(f"✅ Found {len(incidents)} resolved Jumio incidents")
    return incidents

def fetch_entrust_resolved():
    """Fetches resolved incidents from Entrust Statuspage API (past 60 days)."""
    print("📡 [Entrust] Fetching resolved incidents...")
    url = "https://entrust-dcs.statuspage.io/api/v2/incidents.json"
    req = urllib.request.Request(url)

    incidents = []
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Error fetching Entrust API: {e}")
        return incidents

    sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    target_services = VENDOR_CONFIGS["Entrust"]["target_services"]

    for incident in data.get("incidents", []):
        status = incident.get('status', '')

        # Only include resolved incidents
        if status != "resolved":
            continue

        # Parse resolved date
        resolved_at_str = incident.get("resolved_at", "")
        if not resolved_at_str:
            continue

        try:
            resolved_at = datetime.fromisoformat(resolved_at_str.replace("Z", "+00:00"))
        except:
            continue

        if resolved_at < sixty_days_ago:
            continue

        # Filter by target services
        title = incident.get('name', '').strip()
        impact = incident.get('impact', 'none').lower()
        search_text = (title.lower() + " " + impact)

        if not any(service in search_text for service in target_services):
            continue

        # Parse created date
        created_at_str = incident.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except:
            created_at = resolved_at

        duration_hours = round((resolved_at - created_at).total_seconds() / 3600, 2)

        # Extract impact summary
        impact_summary = "N/A"
        if incident.get("incident_updates"):
            impact_summary = incident['incident_updates'][0].get('body', 'N/A')[:200]

        incidents.append({
            "vendor": "Entrust",
            "title": title,
            "affected_services": incident.get('impact', 'Unknown'),
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "resolved_at": resolved_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_hours": duration_hours,
            "status": status,
            "impact_summary": impact_summary,
            "incident_type": "Incident"
        })

    print(f"✅ Found {len(incidents)} resolved Entrust incidents")
    return incidents

# ==========================================
# 3. STORAGE
# ==========================================
def save_resolved_incidents(all_incidents):
    """Saves resolved incidents to CSV."""
    csv_filename = "watch_agent_resolved_incidents.csv"
    keys = [
        "vendor",
        "title",
        "affected_services",
        "created_at",
        "resolved_at",
        "duration_hours",
        "status",
        "impact_summary",
        "incident_type"
    ]

    if not all_incidents:
        print("⚠️  No resolved incidents found in the past 60 days.")
        return

    # Sort by resolved_at descending (most recent first)
    all_incidents.sort(
        key=lambda x: x.get("resolved_at", ""),
        reverse=True
    )

    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for incident in all_incidents:
            writer.writerow(incident)

    os.chmod(csv_filename, 0o600)
    print(f"💾 Saved {len(all_incidents)} resolved incidents to {csv_filename}")

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
def main():
    print("==================================================")
    print("📊 RESOLVED INCIDENTS ARCHIVAL (Past 60 Days)")
    print("==================================================\n")

    all_incidents = []

    # Fetch from all vendors
    all_incidents.extend(fetch_twilio_resolved())
    all_incidents.extend(fetch_jumio_resolved())
    all_incidents.extend(fetch_entrust_resolved())

    # Save to CSV
    save_resolved_incidents(all_incidents)
    print("\n✅ Resolved incidents archival complete. Exiting clean.")

if __name__ == "__main__":
    main()
