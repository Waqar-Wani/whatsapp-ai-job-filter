from pathlib import Path


GROUP_NAME = "Qa Paid Experience"
SPREADSHEET_TITLE = "Filtered Jobs"
WORKSHEET_TITLE = "Filtered Jobs"
SUMMARY_RECIPIENT = "vickywaqar111@gmail.com"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1R5HHz-q7XYZ-AhVpO_Rv-40W7XiJYelBXKHQH3omAhc/edit?gid=0#gid=0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "automation.log"
SESSION_DIR = DATA_DIR / "whatsapp_session"
LAST_PROCESSED_FILE = DATA_DIR / "last_processed.json"
TEMP_SCRAPED_FILE = DATA_DIR / "whatsapp_scraped_temp.json"
OUTREACH_SCRIPT = PROJECT_ROOT / "scripts" / "company_outreach.py"
