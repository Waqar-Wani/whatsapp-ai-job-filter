from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CV_DIR = PROJECT_ROOT / "cv"

SOURCE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1R5HHz-q7XYZ-AhVpO_Rv-40W7XiJYelBXKHQH3omAhc/edit?gid=0#gid=0"
)
SOURCE_WORKSHEET_NAME = "Filtered Jobs"

TRACKING_SPREADSHEET_TITLE = "Job Scrapping - Whatsapp"
TRACKING_WORKSHEET_TITLE = "Finance Jobs"
TRACKING_SPREADSHEET_URL = SOURCE_SHEET_URL
TRACKING_HEADERS = [
    "Date",
    "Company",
    "Location",
    "Contact Email",
    "Outreach Status",
    "Sent At",
]

GOOGLE_SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"

FINANCE_SENDER_EMAIL = "saimashafidar08@gmail.com"
FINANCE_GMAIL_OAUTH_CLIENT_SECRET_FILE = CONFIG_DIR / "Saima_gmail_oauth_client_secret.json"
FINANCE_GMAIL_TOKEN_FILE = DATA_DIR / "finance_saima_gmail_token.json"
FINANCE_REPLY_TO = ""

FINANCE_TEMPLATE_FILE = TEMPLATES_DIR / "Saima Email_template.txt"
FINANCE_CV_FILE = CV_DIR / "Finance_Saima_Dar_Resume.pdf"
FINANCE_SUBJECT_TEMPLATE = "Application for Finance Role"
FINANCE_MAX_EMAILS_PER_RUN = int(os.getenv("FINANCE_MAX_EMAILS_PER_RUN", "3"))
FINANCE_SECONDS_BETWEEN_EMAILS = float(os.getenv("FINANCE_SECONDS_BETWEEN_EMAILS", "20"))
FINANCE_MAX_SEND_RETRIES = int(os.getenv("FINANCE_MAX_SEND_RETRIES", "3"))
FINANCE_RATE_LIMIT_COOLDOWN_SECONDS = float(os.getenv("FINANCE_RATE_LIMIT_COOLDOWN_SECONDS", "120"))
FINANCE_MAX_CONSECUTIVE_RATE_LIMITS = int(os.getenv("FINANCE_MAX_CONSECUTIVE_RATE_LIMITS", "2"))

FINANCE_LOG_FILE = LOG_DIR / "finance_mailer.log"
