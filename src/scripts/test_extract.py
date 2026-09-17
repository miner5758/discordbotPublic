"""Run extraction against a few URLs without Discord or the spreadsheet in the way."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

load_dotenv(SRC_DIR / "resources" / "file.env", override=True)

from sheets_cog import ExtractionError, SheetsCog

URLS = [
    "https://ats.rippling.com/boom-supersonic/jobs/4053f749-3d30-4d71-a64c-5fa79e162bbf",
    "https://lifeattiktok.com/search/7527615375778416914",
    "https://example.com/this-page-does-not-exist-404",
]


def parse_args(argv):
    """URL... [--embed TITLE DESCRIPTION SITE] - the fake embed applies to every URL."""
    embed = None
    if "--embed" in argv:
        index = argv.index("--embed")
        title, description, site = (argv[index + 1 : index + 4] + [None] * 3)[:3]
        embed = {"title": title, "description": description, "site": site}
        argv = argv[:index]
    return argv or URLS, embed


def main():
    cog = SheetsCog(None)
    urls, embed = parse_args(sys.argv[1:])

    for url in urls:
        print("=" * 70)
        print(url)
        try:
            result = cog.extract(url, embed)
        except ExtractionError as error:
            print(f"  REJECTED: {error}")
            continue
        print(f"  source:     {result.source.value}")
        print(f"  name:       {result.name}")
        print(f"  role:       {result.role_type.value}")
        print(f"  type:       {result.opportunity_type.value}")
        print(f"  opens:      {result.open_date}")
        print(f"  closes:     {result.close_date}")
        print(f"  summary:    {result.summary}")


if __name__ == "__main__":
    main()
