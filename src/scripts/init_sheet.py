"""One-off: wipe Sheet1 and write the header row. Run from anywhere."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

from google.oauth2 import service_account
from googleapiclient.discovery import build

from sheets_cog import SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_ID

HEADERS = [
    "Name",
    "Role Type",
    "Opportunity Type",
    "Summary",
    "Open Date",
    "Close Date",
    "Posted By",
    "Date Added",
    "Link",
]


def main():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    values = sheets.spreadsheets().values()

    existing = values.get(spreadsheetId=SPREADSHEET_ID, range="Sheet1!A1:A").execute()
    rows = len(existing.get("values", []))
    print(f"Sheet1 currently holds {rows} row(s). This will delete all of them.")
    if input("Type WIPE to continue: ").strip() != "WIPE":
        print("Aborted.")
        return

    values.clear(spreadsheetId=SPREADSHEET_ID, range="Sheet1", body={}).execute()
    values.update(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A1:I1",
        valueInputOption="RAW",
        body={"values": [HEADERS]},
    ).execute()
    print("Done. Headers written to A1:I1.")


if __name__ == "__main__":
    main()
