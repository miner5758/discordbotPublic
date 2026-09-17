"""Delete sheet rows once they have been there longer than their type allows."""

import calendar
import datetime
import logging

from models import OpportunityType

log = logging.getLogger(__name__)

DATE_FORMAT = "%B %d, %Y"
DEFAULT_MONTHS = 6
MONTHS_BY_TYPE = {
    OpportunityType.INTERNSHIP.value: 8,
    OpportunityType.RESEARCH_PROGRAM.value: 8,
    OpportunityType.CONFERENCE.value: 4,
}

# Column positions in a row read from A2:I.
NAME, OPPORTUNITY_TYPE, DATE_ADDED = 0, 2, 7


def months_before(day, months):
    month = day.month - months
    year = day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def cell(row, index):
    return row[index].strip() if len(row) > index and row[index] else ""


def expired(rows, today=None):
    """Yield (row_index, name, type, added) for rows past their lifetime.

    row_index is the 0-based position in `rows`, which came from A2 - so it is also
    the API's 0-based sheet row minus one.
    """
    today = today or datetime.date.today()
    for index, row in enumerate(rows):
        raw = cell(row, DATE_ADDED)
        try:
            added = datetime.datetime.strptime(raw, DATE_FORMAT).date()
        except ValueError:
            # No usable date means we cannot know its age, so leave it alone.
            continue
        kind = cell(row, OPPORTUNITY_TYPE)
        lifetime = MONTHS_BY_TYPE.get(kind, DEFAULT_MONTHS)
        if added <= months_before(today, lifetime):
            yield index, cell(row, NAME), kind, added


def purge(sheets, spreadsheet_id, sheet_name="Sheet1", dry_run=False):
    """Delete expired rows. Returns the list of (name, type, added) removed."""
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A2:I")
        .execute()
        .get("values", [])
    )
    doomed = list(expired(rows))
    for _, name, kind, added in doomed:
        log.info("%s expired row: %s (%s, added %s)", "Would delete" if dry_run else "Deleting", name, kind, added)
    if not doomed or dry_run:
        return [(name, kind, added) for _, name, kind, added in doomed]

    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = next(
        s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == sheet_name
    )
    # Delete bottom-up so earlier deletions do not shift the indices of later ones.
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": index + 1,
                    "endIndex": index + 2,
                }
            }
        }
        for index, *_ in sorted(doomed, reverse=True)
    ]
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()
    return [(name, kind, added) for _, name, kind, added in doomed]
