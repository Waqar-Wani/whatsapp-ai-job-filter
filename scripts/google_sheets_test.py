import argparse
import os
from datetime import datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1R5HHz-q7XYZ-AhVpO_Rv-40W7XiJYelBXKHQH3omAhc/edit?gid=0#gid=0"
DEFAULT_WORKSHEET = "Filtered Jobs"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_client(service_account_file: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(service_account_file, scopes=scopes)
    return gspread.authorize(creds)


def ensure_worksheet(spreadsheet, worksheet_name: str):
    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=12)

    headers = [
        "Date",
        "Company",
        "Role",
        "Location",
        "Experience",
        "Skills",
        "Contact Email",
    ]
    row1 = ws.row_values(1)
    if row1 != headers:
        ws.update(values=[headers], range_name="A1:G1")
    return ws


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Sheets write/read communication test")
    parser.add_argument("--worksheet", default=DEFAULT_WORKSHEET, help="Worksheet name")
    parser.add_argument(
        "--mode",
        choices=["append", "update"],
        default="append",
        help="append = add a row, update = overwrite row 2",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "config/service_account.json")
    sheet_url = os.getenv("GOOGLE_SHEET_URL", DEFAULT_SHEET_URL)
    sa_path = Path(service_account_file)
    if not sa_path.is_absolute():
        service_account_file = str((PROJECT_ROOT / sa_path).resolve())

    if not os.path.exists(service_account_file):
        raise FileNotFoundError(f"Service account file not found: {service_account_file}")

    client = get_client(service_account_file)
    spreadsheet = client.open_by_url(sheet_url)
    worksheet = ensure_worksheet(spreadsheet, args.worksheet)

    dummy_row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Dummy Company",
        "Dummy QA Engineer",
        "Remote",
        "2+ years",
        "Playwright, Python, API Testing",
        "dummy@example.com",
    ]

    if args.mode == "append":
        worksheet.append_row(dummy_row, value_input_option="USER_ENTERED")
        action = "appended"
    else:
        worksheet.update(values=[dummy_row], range_name="A2:G2")
        action = "updated row 2"

    # Read back last row to verify communication.
    all_values = worksheet.get_all_values()
    last_row = all_values[-1] if len(all_values) > 1 else []

    print("Google Sheets communication test: SUCCESS")
    print(f"Spreadsheet: {spreadsheet.title}")
    print(f"Worksheet: {worksheet.title}")
    print(f"Action: {action}")
    print("Last row read-back:")
    print(last_row)


if __name__ == "__main__":
    main()
