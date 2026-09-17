"""Ask the bot a question about the live sheet without Discord in the way.

    test_ask.py "which software engineering internships are open"
    test_ask.py                       # runs a built-in set of questions
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

load_dotenv(SRC_DIR / "resources" / "file.env", override=True)

from sheets_cog import ExtractionError, SheetsCog

QUESTIONS = [
    "which software engineering internships are open right now",
    "any google roles right now",
    "i want to work on satellites",
    "as a sophomore interested in ML what should i apply for",
    "what's closing soon",
    "any quantum computing internships",
    "is he getting fired?",
]


def main():
    cog = SheetsCog(None)
    for question in sys.argv[1:] or QUESTIONS:
        print("=" * 70)
        print("Q:", question)
        print("-" * 70)
        try:
            answer = cog.ask(question, "tester")
        except ExtractionError as error:
            print("ERROR:", error)
            continue
        print(answer if answer else "(NO_REPLY - bot stays silent)")
        if answer:
            print(f"[{len(answer)} chars]")


if __name__ == "__main__":
    main()
