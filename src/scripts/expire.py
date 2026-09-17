"""Run one expiry sweep by hand. Pass --dry-run to only list what would go."""

import logging
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

from google.oauth2 import service_account
from googleapiclient.discovery import build

import expiry
from sheets_cog import SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_ID


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dry_run = "--dry-run" in sys.argv

    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    removed = expiry.purge(sheets, SPREADSHEET_ID, dry_run=dry_run)

    verb = "would be removed" if dry_run else "removed"
    print(f"{len(removed)} row(s) {verb}.")


if __name__ == "__main__":
    main()
