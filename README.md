# 🚨 AI Vendor Watchdog: Twilio SRE & Architecture

An automated, cloud-native enterprise watchdog system designed to monitor, analyze, and categorize vendor incidents, deprecations, and breaking changes from **Twilio**. 

Powered by **Groq (Llama 3.1)**, it transforms unstructured status logs and changelogs into structured actionable telemetry, specifically evaluated from a **Backbase digital banking platform** perspective.

---

## 📌 Architecture Overview

```text
               ┌───────────────────────────────┐
               │ Twilio API & RSS Changelogs   │
               └───────────────┬───────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ GitHub Actions Cron Job (Runs Hourly)                        │
│                                                              │
│  1. Ingests raw incident & RSS payload                       │
│  2. Ingests context into Groq (Llama 3.1 8B Instant)         │
│  3. Evaluates Backbase Impact & Actionability                │
│  4. Deduplicates & appends to database                       │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
                    [ watchdog_alerts.csv ]
                               │
             ┌─────────────────┴─────────────────┐
             ▼                                   ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│  Google Sheets Sync     │         │ Streamlit Dashboard     │
│  (=IMPORTDATA)          │         │ (dashboard.py)          │
└────────────┬────────────┘         └─────────────────────────┘
             │
             ▼
┌─────────────────────────┐
│ Looker Studio Dashboard │
└─────────────────────────┘

```

1. **Data Ingestion:** Fetches unresolved incidents from the Twilio Status REST API (`status.twilio.com`) and RSS changelogs from Twilio Developer Portal.
2. **AI Intelligence Engine:** Uses Groq (`llama-3.1-8b-instant`) with strict JSON schema outputs to extract product impacts, issue types, and calculate **Backbase actionability**.
3. **Automated Storage Pipeline:** Deduplicates alerts by unique titles and writes directly to `watchdog_alerts.csv`.
4. **Data Synchronization:** Automatically streams updates to Google Sheets via `=IMPORTDATA()` to feed live Looker Studio executive dashboards.

---

## 🛠️ Key Features

* **Backbase Actionability Analysis:** Evaluates every incident against internal Backbase operations, automatically assigning action statuses (`Immediate Action`, `Monitor`, `Code Migration Required`, `No Action`) alongside concise AI-generated justifications.
* **100% Serverless Execution:** Scheduled to run automatically every hour via **GitHub Actions** workflows without needing external hosting infrastructure.
* **Persistent Deduplication:** Features a smart CSV reading engine that prevents repeated incident logging across hourly runs while preserving full history.
* **Automated Data Sanitation:** Intercepts `null`, empty, or missing LLM key values prior to database write, eliminating broken dashboard filters.
* **Strict Service Filtering:** Filters noise by targeting specific core communications services (*Programmable Messaging, Short Codes, SendGrid, SMS, Sender ID, Programmable Chat*).

---

## 📊 Database Schema (`watchdog_alerts.csv`)

| Column Name | Type | Description | Example Value |
| --- | --- | --- | --- |
| `logged_at` | Timestamp | Date/time incident was logged by Watchdog | `2026-08-13 18:25:22` |
| `category` | String | System classification category | `SRE Incident` / `Architecture Deprecation` |
| `title` | String | Heading of the vendor notice | `MMS Delivery Receipt Delays` |
| `product_impacted` | String | Specific Twilio product impacted | `Twilio Short Codes` |
| `type` | String | Issue behavior classification | `Degraded Performance` / `Breaking Change` |
| `status_or_date` | String | Current vendor status or sunset date | `Investigating` / `2026-10-01` |
| `impact_summary` | String | One-sentence issue breakdown | `Delays delivering receipt callbacks to T-Mobile subscribers.` |
| `backbase_action_required` | String | Required engineering/ops response | `Monitor` / `Immediate Action` |
| `backbase_rationale` | String | AI-generated rationale for Backbase | `Core messaging remains functional; impact limited to receipts.` |

---

## 🚀 Local Setup & Installation

### 1. Prerequisites

* Python 3.10+
* Groq API Key ([Get one here](https://console.groq.com/))

### 2. Clone Repository & Install Dependencies

```bash
git clone [https://github.com/abhishek883388/ai_watch_marketplace.git](https://github.com/abhishek883388/ai_watch_marketplace.git)
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

```bash
python twilio_watchdog.py

```

---

## 🌩️ GitHub Actions Continuous Integration

The headless runner is defined in `.github/workflows/watchdog_cron.yml`. It runs automatically every hour via cron trigger or manually via `workflow_dispatch`.

### Repository Configuration

1. Go to **Settings > Secrets and variables > Actions** in your GitHub repository.
2. Add a new secret:
* **Name:** `GROQ_API_KEY`
* **Value:** Your Groq API key string.


3. Under **Settings > Actions > General > Workflow permissions**, ensure **Read and write permissions** are enabled so the bot can commit updated database files back to the branch.

---

## 📈 Dashboard Integrations

### Streamlit Local Dashboard

To launch the interactive local monitoring UI:

```bash
streamlit run dashboard.py

```

### Google Sheets / Looker Studio Live Feed

To connect your database directly to Google Sheets (and Looker Studio):

1. Open a Google Sheet.
2. In Cell `A1`, enter the following dynamic CSV import formula:
```excel
=IMPORTDATA("[https://raw.githubusercontent.com/abhishek883388/ai_watch_marketplace/main/watchdog_alerts.csv](https://raw.githubusercontent.com/abhishek883388/ai_watch_marketplace/main/watchdog_alerts.csv)")

```


3. Connect the Google Sheet as the data source in **Google Looker Studio**.

---

## 📄 License

This project is open-source under the MIT License.

```

```
