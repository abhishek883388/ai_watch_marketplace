# 🚨 AI Vendor Watch Agent: Multi-Vendor SRE & Architecture Monitoring

An automated, cloud-native enterprise watch agent system designed to monitor, analyze, and categorize vendor incidents, deprecations, and breaking changes from **multiple critical vendors**: **Twilio**, **Jumio**, and **Entrust**.

Powered by **OpenAI API** (via Groq endpoint), it transforms unstructured status logs and changelogs into structured actionable telemetry, specifically evaluated from a **Backbase digital banking platform** perspective with deadline/urgency tracking.

---

## 📌 Architecture Overview

```text
┌────────────────────────────────────────────────────────────┐
│ Multi-Vendor Data Sources                                  │
├────────────────────────────────────────────────────────────┤
│ • Twilio Status API & RSS Changelog                        │
│ • Jumio Monitor RSS Feed                                   │
│ • Entrust DCS Statuspage API                               │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ GitHub Actions Cron Job (Runs Hourly)                        │
│                                                              │
│  1. twilio_watch_agent.py   - Twilio incidents & deprecations  │
│  2. jumio_watch_agent.py    - Jumio incidents & deprecations   │
│  3. entrust_watch_agent.py  - Entrust incidents & deprecations │
│  4. deadline_checker.py     - Urgency & deadline tracking      │
│  5. OpenAI + Groq API integration for analysis                │
│  6. Deduplication & database write                            │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
              [ watch_agent_alerts.csv ]
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│ Google Sheets Sync       │     │ Streamlit Dashboard      │
│ (=IMPORTDATA)            │     │ (dashboard.py)           │
└───────────┬──────────────┘     └──────────────────────────┘
            │
            ▼
┌──────────────────────────┐
│ Looker Studio Dashboard  │
│ (Executive Dashboards)   │
└──────────────────────────┘

```

1. **Multi-Vendor Data Ingestion:** 
   - Twilio: Status REST API + RSS changelogs
   - Jumio: Monitor RSS feed
   - Entrust: Statuspage.io JSON API
2. **AI Intelligence Engine:** Uses OpenAI API (via Groq endpoint) with strict JSON schema outputs to extract product impacts, issue types, and calculate **Backbase actionability** and **deadline urgency**.
3. **Deadline & Urgency Tracking:** Automatically detects and categorizes deadlines with urgency levels (OVERDUE, URGENT, UPCOMING, LOW PRIORITY).
4. **Automated Storage Pipeline:** Deduplicates alerts by vendor + title and appends to `watch_agent_alerts.csv` with full audit trail.
5. **Data Synchronization:** Automatically streams updates to Google Sheets via `=IMPORTDATA()` to feed live Looker Studio executive dashboards.

---

## 🛠️ Key Features

* **Multi-Vendor Monitoring:** Simultaneously monitors **three critical vendors** (Twilio, Jumio, Entrust) with vendor-specific service filters and intelligence engines.
* **Backbase Actionability Analysis:** Evaluates every incident against internal Backbase operations, automatically assigning action statuses (`OVERDUE - Action Required`, `Immediate Action`, `Code Migration Required`, `Monitor`, `Assessment Needed`, `No Action`) alongside concise AI-generated justifications.
* **Deadline & Urgency Tracking:** Automatically detects and extracts deadlines from status updates, categorizing them by urgency (OVERDUE, URGENT, UPCOMING, LOW PRIORITY) with countdown timers.
* **100% Serverless Execution:** Scheduled to run automatically every hour via **GitHub Actions** workflows without needing external hosting infrastructure.
* **Persistent Deduplication:** Features a smart CSV reading engine that prevents repeated incident logging across hourly runs by matching vendor + title, while preserving full historical audit trail.
* **Automated Data Sanitation:** Intercepts `null`, empty, or missing LLM key values prior to database write, eliminating broken dashboard filters.
* **Historical Incident Archival:** Automatically captures resolved incidents from the past 60 days with duration metrics and impact summaries in a separate CSV for trend analysis and incident post-mortems.
* **Vendor-Specific Service Filtering:**
  - **Twilio:** Programmable Messaging, SMS, Short Codes, SendGrid, Sender ID, Programmable Chat
  - **Jumio:** Identity Verification (all variants), PerformNetVerify API, Doc Proof, Liveness
  - **Entrust:** Digital Card, Mobile SDK, Card Solution, Issuer TSP, Apple Pay, Google Pay, Push Notifications

---

## 📊 Database Schemas

### Active Alerts (`watch_agent_alerts.csv`)

| Column Name | Type | Description | Example Value |
| --- | --- | --- | --- |
| `logged_at` | Timestamp | Date/time incident was logged by Watch Agent | `2026-08-18 18:23:02` |
| `vendor` | String | Vendor source | `Twilio` / `Jumio` / `Entrust` |
| `category` | String | System classification category | `SRE Incident` / `Architecture Deprecation` |
| `title` | String | Heading of the vendor notice | `SMS Delivery Delays from Twilio to T-Mobile Germany` |
| `product_impacted` | String | Specific vendor product impacted | `Twilio SMS` / `Jumio Android SDK` / `Entrust Digital Card` |
| `type` | String | Issue behavior classification | `Delays` / `Breaking Change` / `Compliance` / `Outage` |
| `status_or_date` | String | Current vendor status or sunset/deadline date | `Resolved` / `2026-10-01` / `None Specified` |
| `impact_summary` | String | One-sentence issue breakdown | `SMS delivery is experiencing delays for T-Mobile network subscribers in Germany.` |
| `backbase_action_required` | String | Required engineering/ops response | `OVERDUE - Action Required` / `Immediate Action` / `Monitor` / `Code Migration Required` / `Assessment Needed` |
| `backbase_rationale` | String | AI-generated rationale for Backbase | `The issue is being monitored and no immediate action is required.` |

### Historical Resolved Incidents (`watch_agent_resolved_incidents.csv`)

Automatically archival of resolved incidents from the **past 60 days**, regenerated hourly:

| Column Name | Type | Description |
| --- | --- | --- |
| `vendor` | String | Vendor source (Twilio, Jumio, Entrust) |
| `title` | String | Incident title |
| `affected_services` | String | Impacted services or components |
| `created_at` | Timestamp | Incident creation time |
| `resolved_at` | Timestamp | Incident resolution time |
| `duration_hours` | Float | Total incident duration in hours |
| `status` | String | Final status (typically "resolved") |
| `impact_summary` | String | Brief description of impact |
| `incident_type` | String | Type classification (Outage, Incident, etc.) |

---

## 🚀 Local Setup & Installation

### 1. Prerequisites

* Python 3.10+
* Groq API Key for OpenAI-compatible API access ([Get one here](https://console.groq.com/))

### 2. Clone Repository & Install Dependencies

```bash
git clone https://github.com/abhishek883388/ai_watch_marketplace.git
cd ai_watch_marketplace
pip install -r requirements.txt
```

### 3. Configure Local Environment

Create a `.env` file in the root folder for local testing:

```env
GROQ_API_KEY=gsk_your_actual_groq_api_key_here

```

*(Note: Ensure `.env` is listed in your `.gitignore` file to prevent exposing private keys).*

### 4. Execute Manually

Run individual vendor watch agents:

```bash
# Monitor Twilio incidents & deprecations
python twilio_watch_agent.py

# Monitor Jumio incidents & deprecations
python jumio_watch_agent.py

# Monitor Entrust incidents & deprecations
python entrust_watch_agent.py
```

Or run all three in sequence:

```bash
python twilio_watch_agent.py && python jumio_watch_agent.py && python entrust_watch_agent.py
```

---

## 🌩️ GitHub Actions Continuous Integration

The headless runner is defined in `.github/workflows/watch_agent_cron.yml`. It runs automatically every hour via cron trigger or manually via `workflow_dispatch`.

### Workflow Execution

Each hourly run executes:
1. **Watch Agent Scripts** (in parallel):
   - `twilio_watch_agent.py` - Fetches Twilio incidents & changelogs
   - `jumio_watch_agent.py` - Fetches Jumio monitor incidents & changelogs
   - `entrust_watch_agent.py` - Fetches Entrust DCS incidents & updates
   - Deadline/urgency detection across all vendors
   - Deduplication and CSV database write

2. **Historical Archival**:
   - `fetch_resolved_incidents.py` - Archives resolved incidents from past 60 days
   - Calculates incident duration and impact metrics
   - Updates `watch_agent_resolved_incidents.csv`

3. **Data Persistence**:
   - Auto-commit & push of both CSV files to repository

### Repository Configuration

1. Go to **Settings > Secrets and variables > Actions** in your GitHub repository.
2. Add a new secret:
   - **Name:** `GROQ_API_KEY`
   - **Value:** Your Groq API key string (for OpenAI-compatible API access)
3. Under **Settings > Actions > General > Workflow permissions**, ensure **Read and write permissions** are enabled so the bot can commit updated database files back to the branch.

---

## 📈 Dashboard Integrations

### Streamlit Local Dashboard

To launch the interactive local monitoring UI:

```bash
streamlit run dashboard.py
```

This provides real-time visibility into:
- All vendor incidents and deprecations
- Backbase action required status
- Deadline urgency tracking
- Historical trends and patterns

### Google Sheets / Looker Studio Live Feed

To connect your database directly to Google Sheets (and Looker Studio):

1. Open a Google Sheet.
2. In Cell `A1`, enter the following dynamic CSV import formula:

```excel
=IMPORTDATA("https://raw.githubusercontent.com/abhishek883388/ai_watch_marketplace/main/watch_agent_alerts.csv")
```

3. Connect the Google Sheet as the data source in **Google Looker Studio** to create executive dashboards.

The data automatically refreshes every hour as new watch agent runs complete and push updates to the repository.

---

## 📁 Project Structure

```
ai_watch_marketplace/
├── twilio_watch_agent.py              # Twilio SRE & architecture monitor
├── jumio_watch_agent.py               # Jumio SRE & architecture monitor
├── entrust_watch_agent.py             # Entrust SRE & architecture monitor
├── deadline_checker.py                # Deadline extraction & urgency tracking utility
├── fetch_resolved_incidents.py        # Historical resolved incidents archival (past 60 days)
├── dashboard.py                       # Streamlit monitoring dashboard
├── watch_agent_alerts.csv             # Master alert database (auto-updated hourly)
├── watch_agent_alerts.json            # JSON backup of alerts
├── watch_agent_resolved_incidents.csv # Historical resolved incidents (auto-updated hourly)
├── requirements.txt                   # Python dependencies
├── README.md                          # This file
└── .github/workflows/
    └── watch_agent_cron.yml           # GitHub Actions hourly trigger
```

---

## 🧠 AI Analysis Pipeline

Each watch agent script follows this analysis flow:

### 1. **Data Fetching**
- Pulls raw incidents from vendor-specific APIs/RSS feeds
- Filters by vendor-specific service keywords
- Extracts title, status, summary, and dates

### 2. **AI Enrichment** (OpenAI via Groq)
- Sends incidents to LLM with Backbase context
- Outputs structured JSON with:
  - Product impact classification
  - Issue type categorization
  - Backbase-specific action required
  - AI-generated rationale
  - Deadline extraction (if present)

### 3. **Deadline Analysis**
- Extracts dates from status strings
- Calculates urgency level:
  - **OVERDUE:** Past deadline
  - **URGENT:** < 7 days to deadline
  - **UPCOMING:** 7-30 days to deadline
  - **LOW PRIORITY:** > 30 days or no deadline

### 4. **Deduplication & Storage**
- Checks `watch_agent_alerts.csv` for duplicates (vendor + title match)
- Appends new alerts with full audit trail
- Preserves historical records

---

## ⚙️ Customization Guide

### Modify Service Filters

Edit the `TARGET_SERVICES` list in each watch agent script:

**Twilio example:**
```python
TARGET_SERVICES = [
    "programmable messaging",
    "programmable chat",
    "sender id",
    "sendgrid",
    "sms",
    "short code"
]
```

### Adjust Analysis Prompts

Modify the LLM prompt templates in each watch agent script's `analyze_status()` and `analyze_changelog()` functions to customize:
- Action classification criteria
- Backbase impact assessment
- Output fields

### Change Execution Schedule

Edit `.github/workflows/watch_agent_cron.yml`:
```yaml
on:
  schedule:
    - cron: '0 * * * *'  # Change this to adjust frequency
```

Standard cron format: `minute hour day month day-of-week`

---

## 📊 Monitoring & Alerts

The Streamlit dashboard provides:
- Real-time incident summary by vendor
- Action required breakdown
- Deadline urgency heatmap
- Historical trend analysis
- CSV export capabilities

---

## 🔧 Troubleshooting

### Missing Alerts
1. Check `GROQ_API_KEY` is set correctly in GitHub Actions Secrets
2. Verify vendor status pages are accessible (check URLs in watch agent scripts)
3. Review GitHub Actions logs for specific errors

### Duplicate Entries
The system deduplicates by (vendor, title) pair. If you see duplicates:
1. Check the exact title match in CSV
2. Manual CSV cleanup may be needed for historical data

### Deadline Detection Issues
The `deadline_checker.py` module supports multiple date formats. If deadlines aren't extracted:
1. Check the date format in vendor alerts
2. Add new format to `formats` list in `parse_date()` function

---

## 📄 License

This project is open-source under the MIT License.
