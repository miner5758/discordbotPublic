import asyncio
import datetime
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import discord
from discord.ext import commands
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models import Opportunity, unreadable_page

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"
PROMPT_FILE = BASE_DIR / "resources" / "gem.md"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1oXxHr3n1uGL2ZPcMDFiVFUQKASmQ4k5WMTlbJhrbCbI"
APPEND_RANGE = "Sheet1!A2:I"
LINK_COLUMN_RANGE = "Sheet1!I2:I"

CHANNEL_NAME = "opportunities"

# Capacity varies a lot between these, and 503/429 bursts are common on the newest ones,
# so a failed attempt moves to the next model rather than retrying the same one.
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
]
RETRY_CODES = {429, 503}

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")

SHEET_LINK = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=sharing"


class ExtractionError(Exception):
    """Message is shown to the user, so keep it short and plain.

    page_unreadable separates a link we will never parse (write a placeholder row) from
    a transient outage (write nothing, since a later retry would succeed).
    """

    def __init__(self, reason, page_unreadable=False):
        super().__init__(reason)
        self.page_unreadable = page_unreadable


class SheetsCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.prompt = PROMPT_FILE.read_text(encoding="utf-8")
        self.gemini = genai.Client(api_key=os.environ["gemkey"])

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        self.sheets = build(
            "sheets", "v4", credentials=credentials, cache_discovery=False
        )

    # --- links ---

    @staticmethod
    def find_links(text):
        # Trailing punctuation is almost always sentence punctuation, not part of the URL.
        return [match.group().rstrip(".,;:!?)]}>") for match in URL_PATTERN.finditer(text)]

    @staticmethod
    def normalize(link):
        if link.lower().startswith("www."):
            link = "https://" + link
        parts = urlparse(link)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if not key.lower().startswith("utm_")
        ]
        host = parts.netloc.lower().removeprefix("www.")
        return urlunparse(
            (
                parts.scheme.lower(),
                host,
                parts.path.rstrip("/"),
                "",
                urlencode(query),
                "",
            )
        )

    # --- sheet ---

    def existing_links(self):
        rows = (
            self.sheets.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=LINK_COLUMN_RANGE)
            .execute()
            .get("values", [])
        )
        return {self.normalize(row[0]) for row in rows if row and row[0].strip()}

    @staticmethod
    def _escape(value):
        # USER_ENTERED keeps links clickable, which also means a leading = or + would be
        # evaluated as a formula.
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    def append_row(self, opportunity, link, posted_by):
        row = [
            self._escape(opportunity.name),
            opportunity.role_type.value,
            opportunity.opportunity_type.value,
            self._escape(opportunity.summary),
            opportunity.open_date,
            opportunity.close_date,
            posted_by,
            datetime.date.today().strftime("%B %d, %Y"),
            link,
        ]
        self.sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=APPEND_RANGE,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    # --- extraction ---

    @staticmethod
    def retrieval_failed(response):
        # Absent metadata means the API told us nothing either way, so fall back to the
        # model's own page_read flag rather than rejecting the row.
        entries = []
        for candidate in response.candidates or []:
            metadata = getattr(candidate, "url_context_metadata", None)
            entries.extend(getattr(metadata, "url_metadata", None) or [])
        if not entries:
            return False
        return not any(
            "SUCCESS" in str(getattr(entry, "url_retrieval_status", "")) for entry in entries
        )

    def generate(self, link):
        today = datetime.date.today().strftime("%B %d, %Y")
        contents = f"Today is {today}. Extract the opportunity at this URL: {link}"
        config = types.GenerateContentConfig(
            system_instruction=self.prompt,
            tools=[types.Tool(url_context=types.UrlContext())],
            response_mime_type="application/json",
            response_schema=Opportunity,
        )

        for attempt, model in enumerate(MODELS):
            last = attempt == len(MODELS) - 1
            try:
                return self.gemini.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except genai_errors.APIError as error:
                if error.code not in RETRY_CODES or last:
                    raise
                log.warning("Gemini %s from %s for %s", error.code, model, link)
                # 429 is a per-minute quota, so it needs a longer wait than a 503 spike.
                time.sleep(20 if error.code == 429 else 2)

    def extract(self, link):
        try:
            response = self.generate(link)
        except Exception as error:
            log.exception("Gemini call failed for %s", link)
            raise ExtractionError("the extractor is unavailable right now") from error

        if self.retrieval_failed(response):
            raise ExtractionError("that page couldn't be loaded", page_unreadable=True)

        opportunity = response.parsed
        if opportunity is None:
            log.error("Unparseable response for %s: %s", link, response.text)
            raise ExtractionError("that posting couldn't be read")
        if not opportunity.page_read:
            raise ExtractionError("that page couldn't be loaded", page_unreadable=True)
        return opportunity

    # --- discord ---

    @staticmethod
    async def react(message, emoji):
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            log.warning("Could not add %s - check the Add Reactions permission", emoji)

    @staticmethod
    async def unreact(message, emoji, user):
        try:
            await message.remove_reaction(emoji, user)
        except discord.HTTPException:
            pass

    async def handle_link(self, link, known, posted_by):
        key = self.normalize(link)
        if key in known:
            return "duplicate"
        try:
            opportunity = await asyncio.to_thread(self.extract, link)
            outcome = "added"
        except ExtractionError as error:
            if not error.page_unreadable:
                raise
            opportunity = unreadable_page()
            outcome = "unfilled"
        await asyncio.to_thread(self.append_row, opportunity, link, posted_by)
        known.add(key)
        return outcome

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if getattr(message.channel, "name", None) != CHANNEL_NAME:
            return

        content = message.content.strip()
        lowered = content.lower()
        username = message.author.display_name

        if lowered == "daniel shapero give me the link to the spreadsheet":
            await message.channel.send(f"Here you go {username}: {SHEET_LINK}")
            return
        if lowered == "daniel shapero are we getting internships?":
            await message.channel.send(
                "Yes, ALL of you are getting internships and are going to become rich!"
            )
            return

        # Extract from the original text: Greenhouse, Workday and Lever paths are
        # case-sensitive, so matching against a lowercased copy would corrupt them.
        links = self.find_links(content)
        if not links:
            return

        await self.react(message, "⏳")
        added = unfilled = duplicates = failed = 0
        try:
            known = await asyncio.to_thread(self.existing_links)
            for link in links:
                try:
                    result = await self.handle_link(link, known, username)
                except ExtractionError as error:
                    failed += 1
                    await message.channel.send(f"Skipped <{link}> — {error}")
                    continue
                if result == "added":
                    added += 1
                elif result == "unfilled":
                    unfilled += 1
                    await message.channel.send(
                        f"Added <{link}> but couldn't open the page, so that row needs "
                        f"filling in by hand."
                    )
                else:
                    duplicates += 1
        except HttpError:
            log.exception("Spreadsheet request failed")
            failed += 1
            await message.channel.send("Couldn't reach the spreadsheet.")
        except Exception:
            log.exception("Unexpected failure handling %s", links)
            failed += 1
            await message.channel.send("Something went wrong on my end.")
        finally:
            await self.unreact(message, "⏳", self.bot.user)

        if added:
            await self.react(message, "✅")
        if unfilled:
            await self.react(message, "⚠️")
        if not (added or unfilled):
            await self.react(message, "🔁" if duplicates and not failed else "❌")
