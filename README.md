# Job Scrapping - WhatsApp Automation

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Playwright" src="https://img.shields.io/badge/Playwright-Automation-2EAD33?style=for-the-badge&logo=playwright&logoColor=white">
  <img alt="OpenRouter" src="https://img.shields.io/badge/OpenRouter-LLM-111827?style=for-the-badge">
  <img alt="Google Sheets" src="https://img.shields.io/badge/Google%20Sheets-Connected-34A853?style=for-the-badge&logo=googlesheets&logoColor=white">
  <img alt="Gmail API" src="https://img.shields.io/badge/Gmail-API-EA4335?style=for-the-badge&logo=gmail&logoColor=white">
</p>

<p align="center">
  <b>WhatsApp Group Scraper → AI Job Filtering → Google Sheets → Company Outreach Emails</b>
</p>

---

## 🌈 What This Program Does

This project automates the full pipeline:

1. Opens WhatsApp Web with persistent login session.
2. Finds and opens group: (`Mention group name0`).
3. Scrolls chat history for ~30 seconds and expands truncated messages (`Read more`).
4. Scrapes messages (sender, text, timestamp) to local temp JSON.
5. Filters messages with OpenRouter AI into structured job fields.
6. Saves relevant jobs to Google Sheet (`Filtered Jobs`) with dedup logic.
7. Sends outreach emails to company contacts with CV attachment via Gmail API.
8. Ensures already-contacted companies/rows are not emailed again.

---

## 🧭 Visual Flow (Infographic)

```text
┌───────────────────────┐
│  WhatsApp Web Group   │
│  "Qa Paid Experience" │
└───────────┬───────────┘
            │ scrape + expand + scroll
            ▼
┌───────────────────────────────┐
│ data/whatsapp_scraped_temp.json│
└───────────┬───────────────────┘
            │ new messages after last_processed
            ▼
┌───────────────────────────────┐
│ OpenRouter AI (JSON output)   │
│ relevant/company/role/...     │
└───────────┬───────────────────┘
            │ dedup + append
            ▼
┌───────────────────────────────┐
│ Google Sheet: Filtered Jobs   │
└───────────┬───────────────────┘
            │ outreach trigger (main flow)
            ▼
┌───────────────────────────────┐
│ company_outreach.py           │
│ sends mail + CV attachment    │
│ tracks sent records           │
└───────────────────────────────┘
```

---

## 📁 Project Structure

```text
Job Scrapping - Whatsapp/
├── main.py
├── run_main_cron.sh
├── requirements.txt
├── .env
├── .env.example
├── README.md
├── QA_Waqar_Wani__Resume.pdf
├── config/
│   └── service_account.json
├── templates/
│   └── company_email_template.txt
├── scripts/
│   ├── company_outreach.py
│   ├── sheet_update_mail_trigger.py
│   ├── ai_health_check.py
│   └── google_sheets_test.py
├── data/
│   ├── last_processed.json
│   ├── whatsapp_scraped_temp.json
│   ├── sent_company_emails.json
│   ├── sheet_watch_state.json
│   └── whatsapp_session/
└── logs/
    └── automation.log
```

---

## ⚙️ Setup

### 1) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 2) Configure environment

Create `.env` from `.env.example` and fill values:

```env
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_SITE_URL=
OPENROUTER_SITE_NAME=Job Scrapping - Whatsapp

GMAIL_SENDER_EMAIL=(your gmail address)
GMAIL_OAUTH_CLIENT_SECRET_FILE=config/gmail_oauth_client_secret.json
GMAIL_TOKEN_FILE=data/gmail_token.json
GMAIL_REPLY_TO=(your personal email id)

GOOGLE_SERVICE_ACCOUNT_FILE=config/service_account.json
GOOGLE_SHEET_URL=(your google sheet url))

CV_FILE_PATH=QA_Waqar_Wani__Resume.pdf
OUTREACH_WORKSHEET=Filtered Jobs
OUTREACH_TEMPLATE_FILE=templates/company_email_template.txt
OUTREACH_SUBJECT_TEMPLATE=Application for {role} - {company}

RUN_OUTREACH_ON_MAIN=true
SHEET_WATCH_INTERVAL_SECONDS=60
SHEET_WATCH_SEND_ON_START=false
```

### 3) Google Sheets access

- Place service account key at `config/service_account.json`
- Share target Google Sheet with service account `client_email` as **Editor**

### 4) Gmail API setup

- Create Google OAuth desktop app credentials in Google Cloud
- Save the OAuth client JSON file at `config/gmail_oauth_client_secret.json`
- On first send, the script will open the Google consent flow and create `data/gmail_token.json`
- Optionally set `GMAIL_REPLY_TO` to your preferred inbox

---

## ▶️ Run Modes

### Main full pipeline

> Recommended: clear Playwright browser cache before each run to avoid stale profile lock files and session artifacts.
>
> - Windows:
>   ```powershell
>   powershell -ExecutionPolicy Bypass -File .\scripts\clear_browser_cache.ps1
>   ```
> - Auto-run from code (default): `main.py` now calls the same script for Windows if `CLEAR_BROWSER_CACHE_BEFORE_RUN=true` (default).
> - If Playwright reports `ProcessSingleton` / profile lock error repeatedly, the app now falls back to a temporary profile directory, though this may require a manual re-login to WhatsApp Web.

```bash
source .venv/bin/activate
python main.py
```

### AI health check

```bash
source .venv/bin/activate
python scripts/ai_health_check.py --prompt "Say only: AI working"
```

### Google Sheets test

```bash
source .venv/bin/activate
python scripts/google_sheets_test.py --mode append
```

### Outreach only

```bash
source .venv/bin/activate
python scripts/company_outreach.py --limit 1
```

### Watch sheet and trigger outreach on new rows

```bash
source .venv/bin/activate
python scripts/sheet_update_mail_trigger.py
```

### Clear Playwright browser cache on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clear_browser_cache.ps1
```

Use `-FullReset` only if you also want to clear additional browser storage:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clear_browser_cache.ps1 -FullReset
```

Use `-LogoutReset` if you want a full session wipe that logs WhatsApp Web out and forces a fresh browser profile:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\clear_browser_cache.ps1 -LogoutReset
```

---

## 📬 Output Schema (Google Sheet)

Columns:

1. `Date`
2. `Company`
3. `Role`
4. `Location`
5. `Experience`
6. `Skills`
7. `Contact Email`

---

## 🛡️ Dedup + Safety Logic

- Message dedup by: `sender + timestamp + text`
- AI only processes messages after `data/last_processed.json`
- Sheet dedup checks existing rows before append
- Outreach skips rows already sent by:
  - sheet columns (`Outreach Sent At`)
  - local tracker (`data/sent_company_emails.json`)
- Cron lock file prevents overlapping runs:
  - `data/.main_cron.lock`

---

## ⏰ Cron Automation (Every 5 Minutes)

Add cron:

```bash
(crontab -l 2>/dev/null; echo '*/5 * * * * /Users/dev/GitHub/Job\ Scrapping\ -\ Whatsapp/run_main_cron.sh') | crontab -
```

Verify:

```bash
crontab -l
```

Manual test:

```bash
/Users/waqar/GitHub/Job\ Scrapping\ -\ Whatsapp/run_main_cron.sh
```

---

## 🧪 Troubleshooting

### No new rows in sheet
- Check `logs/automation.log`
- Confirm `last_processed.json` is not ahead of current chat messages
- Ensure OpenRouter key/model are valid

### Gmail not sending
- Use Gmail App Password (not normal password)
- Confirm 2FA is enabled for Gmail account

### Sheet write fails
- Re-check sharing permission for service account email
- Verify `GOOGLE_SHEET_URL` and worksheet name

### WhatsApp scrape misses messages
- Main flow now scrolls up for 30 seconds and clicks `Read more`
- If needed, increase scroll duration in `main.py`

---

## 📘 Notes

- `logs/automation.log` is the single unified log file for main + outreach + trigger flows.
- Keep `.env` and `config/service_account.json` private.
- Rotate API keys/app passwords if exposed.

