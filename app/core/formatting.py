from datetime import datetime


def format_sheet_datetime(value: datetime) -> str:
    time_part = value.strftime("%I:%M:%S %p").lstrip("0")
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}, {time_part}"
