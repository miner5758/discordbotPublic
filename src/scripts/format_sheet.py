"""Apply the sheet's look: header, widths, wrapping, dropdowns, banding, deadline
highlights, and a filter. Touches formatting only, never data. Safe to re-run."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

from google.oauth2 import service_account
from googleapiclient.discovery import build

from models import OpportunityType, RoleType
from sheets_cog import SCOPES, SERVICE_ACCOUNT_FILE, SPREADSHEET_ID

SHEET = "Sheet1"
COLUMNS = 9

BLUE = {"red": 0.04, "green": 0.40, "blue": 0.76}
WHITE = {"red": 1, "green": 1, "blue": 1}
BAND = {"red": 0.95, "green": 0.97, "blue": 0.98}
SOON = {"red": 1.00, "green": 0.93, "blue": 0.75}
GONE = {"red": 0.60, "green": 0.60, "blue": 0.60}

# Colour per opportunity type so the column reads at a glance, and one saved filter view
# per group so "just the internships" is one click under Data > Filter views.
T = OpportunityType
TYPE_GROUPS = [
    ("Internships & Co-ops",     [T.INTERNSHIP, T.CO_OP, T.NEW_GRAD],          {"red": 0.85, "green": 0.92, "blue": 1.00}),
    ("Events & Hackathons",      [T.CONFERENCE],                                {"red": 0.93, "green": 0.87, "blue": 0.98}),
    ("Scholarships & Fellowships", [T.SCHOLARSHIP, T.FELLOWSHIP],               {"red": 0.85, "green": 0.95, "blue": 0.87}),
    ("Research",                 [T.RESEARCH_PROGRAM],                          {"red": 0.82, "green": 0.95, "blue": 0.95}),
    ("Programs & Pipelines",     [T.EARLY_INSIGHT, T.MENTORSHIP, T.INTEREST_FORM], {"red": 1.00, "green": 0.96, "blue": 0.80}),
]

WIDTHS = [300, 170, 180, 560, 130, 130, 120, 140, 320]
CENTERED = [1, 2, 4, 5, 6, 7]
DATE_COLUMNS = [4, 5, 7]
# Must stay a full month name: expiry.py parses this column with %B.
DATE_FORMAT = "mmmm d, yyyy"


def rng(sheet_id, rows, start_row=0, start_col=0, end_col=COLUMNS):
    return {
        "sheetId": sheet_id,
        "startRowIndex": start_row,
        "endRowIndex": rows,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }


def column(sheet_id, rows, index):
    return rng(sheet_id, rows, 1, index, index + 1)


def dropdown(sheet_id, rows, index, values):
    return {
        "setDataValidation": {
            "range": column(sheet_id, rows, index),
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in values],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }


def highlight(sheet_id, rows, formula, fmt):
    return {
        "addConditionalFormatRule": {
            "index": 0,
            "rule": {
                "ranges": [column(sheet_id, rows, 5)],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": formula}],
                    },
                    "format": fmt,
                },
            },
        }
    }


def type_colour(sheet_id, rows, value, colour):
    return {
        "addConditionalFormatRule": {
            "index": 0,
            "rule": {
                "ranges": [column(sheet_id, rows, 2)],
                "booleanRule": {
                    "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]},
                    "format": {"backgroundColor": colour},
                },
            },
        }
    }


def filter_view(sheet_id, rows, title, keep):
    hidden = [t.value for t in OpportunityType if t not in keep]
    return {
        "addFilterView": {
            "filter": {
                "title": title,
                "range": rng(sheet_id, rows),
                "criteria": {"2": {"hiddenValues": hidden}},
            }
        }
    }


def build_requests(sheet, rows):
    sid = sheet["properties"]["sheetId"]
    requests = []

    # Clear what a previous run added, so this stays idempotent.
    for _ in sheet.get("conditionalFormats", []):
        requests.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    for band in sheet.get("bandedRanges", []):
        requests.append({"deleteBanding": {"bandedRangeId": band["bandedRangeId"]}})
    for view in sheet.get("filterViews", []):
        requests.append({"deleteFilterView": {"filterId": view["filterViewId"]}})

    requests.append(
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )

    requests.append(
        {
            "repeatCell": {
                "range": rng(sid, 1),
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": BLUE,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                        "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,wrapStrategy,textFormat)",
            }
        }
    )
    requests.append(
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 38},
                "fields": "pixelSize",
            }
        }
    )

    for index, width in enumerate(WIDTHS):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    requests.append(
        {
            "repeatCell": {
                "range": rng(sid, rows, 1),
                "cell": {
                    "userEnteredFormat": {
                        "verticalAlignment": "TOP",
                        "wrapStrategy": "CLIP",
                        "textFormat": {"fontSize": 10},
                    }
                },
                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy,textFormat.fontSize)",
            }
        }
    )
    requests.append(
        {
            "repeatCell": {
                "range": column(sid, rows, 3),
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        }
    )
    for index in CENTERED:
        requests.append(
            {
                "repeatCell": {
                    "range": column(sid, rows, index),
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            }
        )
    for index in DATE_COLUMNS:
        requests.append(
            {
                "repeatCell": {
                    "range": column(sid, rows, index),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": DATE_FORMAT}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

    requests.append(dropdown(sid, rows, 1, [r.value for r in RoleType]))
    requests.append(dropdown(sid, rows, 2, [o.value for o in OpportunityType]))

    requests.append(
        {
            "addBanding": {
                "bandedRange": {
                    "range": rng(sid, rows),
                    "rowProperties": {
                        "headerColor": BLUE,
                        "firstBandColor": WHITE,
                        "secondBandColor": BAND,
                    },
                }
            }
        }
    )

    # Order matters: rules are inserted at index 0, so the one added last wins.
    requests.append(
        highlight(sid, rows, "=AND(ISNUMBER($F2), $F2<TODAY())",
                  {"textFormat": {"foregroundColor": GONE, "strikethrough": True}})
    )
    requests.append(
        highlight(sid, rows, "=AND(ISNUMBER($F2), $F2>=TODAY(), $F2-TODAY()<=14)",
                  {"backgroundColor": SOON, "textFormat": {"bold": True}})
    )

    for _, types_, colour in TYPE_GROUPS:
        for t in types_:
            requests.append(type_colour(sid, rows, t.value, colour))
    for title, types_, _ in TYPE_GROUPS:
        requests.append(filter_view(sid, rows, title, types_))

    requests.append({"setBasicFilter": {"filter": {"range": rng(sid, rows)}}})
    return requests


def main():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    meta = sheets.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID, fields="sheets(properties,bandedRanges,conditionalFormats,filterViews)"
    ).execute()
    sheet = next(s for s in meta["sheets"] if s["properties"]["title"] == SHEET)
    rows = sheet["properties"]["gridProperties"]["rowCount"]

    requests = build_requests(sheet, rows)
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body={"requests": requests}
    ).execute()
    print(f"Applied {len(requests)} formatting changes to {SHEET}.")


if __name__ == "__main__":
    main()
