import asyncio
import datetime
import difflib
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

from models import Opportunity, Source, unreadable_page

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

# The bot is named after a real LinkedIn exec who gets mentioned in normal conversation,
# so a name alone never triggers a reply - it also needs one of the intent words below.
NAME_WORDS = {"dan", "danny", "daniel", "shapero", "shap"}
NAME_FUZZY = ("daniel", "shapero")
NAME_FUZZY_CUTOFF = 0.8
SHEET_WORDS = {"sheet", "sheets", "spreadsheet", "spreadsheets", "excel"}
INTERN_WORDS = {"intern", "interns", "internship", "internships", "offer", "offers", "hired", "job", "jobs", "rich"}
HELP_WORDS = {"help", "commands"}
HELP_PHRASES = ("what can you do", "what do you do")

HELP_TEXT = (
    "Here's what I do:\n"
    "• Post a link in this channel and I'll add it to the spreadsheet.\n"
    "• Ask me for the **sheet** or **spreadsheet** and I'll send the link.\n"
    "• Ask me about **internships** if you need a pep talk.\n"
    "Say my name or @ me so I know you're talking to me."
)


class ExtractionError(Exception):
    """Transient failure - nothing is written, since a later retry would succeed.

    Message is shown to the user, so keep it short and plain.
    """


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
        # Absent metadata means the API told us nothing either way, so trust the
        # model's own source claim in that case.
        entries = []
        for candidate in response.candidates or []:
            metadata = getattr(candidate, "url_context_metadata", None)
            entries.extend(getattr(metadata, "url_metadata", None) or [])
        if not entries:
            return False
        return not any(
            "SUCCESS" in str(getattr(entry, "url_retrieval_status", "")) for entry in entries
        )

    @staticmethod
    def build_contents(link, embed):
        today = datetime.date.today().strftime("%B %d, %Y")
        contents = f"Today is {today}. Extract the opportunity at this URL: {link}"
        if embed:
            contents += "\n\nDiscord's link preview for this URL:"
            for label in ("title", "description", "site"):
                if embed.get(label):
                    contents += f"\n  {label.capitalize()}: {embed[label]}"
        return contents

    def generate(self, link, embed):
        contents = self.build_contents(link, embed)
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

    def extract(self, link, embed=None):
        try:
            response = self.generate(link, embed)
        except Exception as error:
            log.exception("Gemini call failed for %s", link)
            raise ExtractionError("the extractor is unavailable right now") from error

        opportunity = response.parsed
        if opportunity is None:
            log.error("Unparseable response for %s: %s", link, response.text)
            raise ExtractionError("that posting couldn't be read")

        # The API reports whether the fetch really succeeded; a model that claims the
        # page anyway gets downgraded to what it could actually have seen.
        if opportunity.source == Source.PAGE and self.retrieval_failed(response):
            opportunity.source = Source.EMBED if embed else Source.URL
            log.warning("Model claimed page for %s but fetch failed; using %s", link, opportunity.source.value)

        if opportunity.source == Source.NONE:
            return unreadable_page()
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

    async def wait_for_embeds(self, message):
        # Discord attaches link previews after the message event fires, via a later
        # edit, so the embeds are almost never present when on_message runs.
        embeds = {}
        for delay in (1.5, 2.0):
            await asyncio.sleep(delay)
            try:
                fresh = await message.channel.fetch_message(message.id)
            except discord.HTTPException:
                break
            for embed in fresh.embeds:
                if not embed.url:
                    continue
                embeds[self.normalize(embed.url)] = {
                    "title": embed.title,
                    "description": embed.description,
                    "site": getattr(embed.provider, "name", None),
                }
            if embeds:
                break
        return embeds

    async def handle_link(self, link, known, posted_by, embed=None):
        key = self.normalize(link)
        if key in known:
            return "duplicate"
        opportunity = await asyncio.to_thread(self.extract, link, embed)
        await asyncio.to_thread(self.append_row, opportunity, link, posted_by)
        known.add(key)
        log.info("Added %s from %s", link, opportunity.source.value)
        return "unfilled" if opportunity.source == Source.NONE else "added"

    # --- chat ---

    @staticmethod
    def words(text):
        return set(re.findall(r"[a-z]+", text.lower()))

    def addressed(self, message):
        if self.bot and self.bot.user in message.mentions:
            return True
        words = self.words(message.content)
        if words & NAME_WORDS:
            return True
        # Short words fuzz too easily ("dial" is one edit from "dan"), so only try the
        # near-miss check on words long enough to plausibly be a misspelled name.
        return any(
            difflib.get_close_matches(word, NAME_FUZZY, n=1, cutoff=NAME_FUZZY_CUTOFF)
            for word in words
            if len(word) >= 5
        )

    @classmethod
    def reply_for(cls, content, username):
        words = cls.words(content)
        lowered = content.lower()
        if words & SHEET_WORDS:
            return f"Here you go {username}: {SHEET_LINK}"
        if words & INTERN_WORDS:
            return "Yes, ALL of you are getting internships and are going to become rich!"
        if words & HELP_WORDS or any(phrase in lowered for phrase in HELP_PHRASES):
            return HELP_TEXT
        return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if getattr(message.channel, "name", None) != CHANNEL_NAME:
            return

        content = message.content.strip()
        username = message.author.display_name

        # Extract from the original text: Greenhouse, Workday and Lever paths are
        # case-sensitive, so matching against a lowercased copy would corrupt them.
        links = self.find_links(content)
        if links:
            await self.process_links(message, links, username)
            return

        if not self.addressed(message):
            return
        reply = self.reply_for(content, username)
        if reply:
            await message.channel.send(reply)

    async def process_links(self, message, links, username):
        await self.react(message, "⏳")
        added = unfilled = duplicates = failed = 0
        try:
            known, embeds = await asyncio.gather(
                asyncio.to_thread(self.existing_links),
                self.wait_for_embeds(message),
            )
            for link in links:
                try:
                    embed = embeds.get(self.normalize(link))
                    result = await self.handle_link(link, known, username, embed)
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
