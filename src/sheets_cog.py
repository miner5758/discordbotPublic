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
from discord.ext import commands, tasks
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import ats
import expiry
from models import Opportunity, Source, unreadable_page

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"
PROMPT_FILE = BASE_DIR / "resources" / "gem.md"
ASK_PROMPT_FILE = BASE_DIR / "resources" / "ask.md"

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
# A sheet word plus one of these is a request for the link, however long the message.
# A sheet word in a longer message without one ("what internships are on the sheet?")
# is a question about its contents and goes to the query path instead.
LINK_REQUEST_WORDS = {"link", "url", "give", "send", "share", "where", "wheres", "show", "get", "gimme", "open", "pull"}
INTERN_WORDS = {"intern", "interns", "internship", "internships", "offer", "offers", "hired", "job", "jobs", "rich"}
HELP_WORDS = {"help", "commands"}
HELP_PHRASES = ("what can you do", "what do you do")
SHORT_MESSAGE = 6

# The query gate: the name must lead, and the message must read as a request. These
# cue words are about shape, not topic - topic is the model's job.
NAME_LEAD_WORDS = 3
REQUEST_CUES = {
    "i", "im", "me", "my", "we", "us", "you", "your", "should", "can", "could",
    "any", "which", "what", "whats", "where", "when", "how", "show", "find", "list",
    "recommend", "suggest", "want", "looking", "interested", "need", "closing",
    "deadline", "open", "available", "best",
}
MIN_QUERY_WORDS = 3
# Cues that mark a real question about contents, as opposed to the pronouns above that
# merely show the message is aimed at someone. The pep talk yields to these.
QUESTION_CUES = REQUEST_CUES - {"i", "im", "me", "my", "we", "us", "you", "your", "can", "could"}
QUERY = object()
NO_REPLY = "NO_REPLY"
ROWS_CACHE_SECONDS = 60
SUMMARY_PREVIEW = 220
DISCORD_LIMIT = 1900

HELP_TEXT = (
    "**Here's what I do**\n"
    "\n"
    "**Add an opportunity** — just post the link in this channel. I'll read the posting "
    "and add it to the spreadsheet. Several links in one message is fine.\n"
    "  ⏳ working · ✅ added · ⚠️ added but I couldn't open the page · 🔁 already in the sheet · ❌ failed\n"
    "\n"
    "**Ask about what's in the sheet** — say my name and ask in plain English:\n"
    "  `dan which software engineering internships are open?`\n"
    "  `dan any google roles right now?`\n"
    "  `dan i want to work on satellites`\n"
    "  `dan as a sophomore interested in ML, what should i apply for?`\n"
    "  `dan what's closing soon?`\n"
    "If nothing matches, I'll say so.\n"
    "\n"
    "**Get the spreadsheet** — say my name and ask for the sheet:\n"
    "  `dan spreadsheet?`\n"
    "  `shapero where's the sheet`\n"
    "  `daniel give me the link to the spreadsheet`\n"
    "\n"
    "**Ask about internships** — `dan are we getting internships?`\n"
    "\n"
    "**Rows expire** — internships and research programs after 8 months, conferences "
    "and events after 4, everything else after 6.\n"
    "\n"
    "**This message** — `dan help` or `daniel what can you do`\n"
    "\n"
    "I answer to **dan**, **daniel**, **shapero**, close misspellings, or an @mention. "
    "Lead with my name so I know you're talking to me."
)


class ExtractionError(Exception):
    """Transient failure - nothing is written, since a later retry would succeed.

    Message is shown to the user, so keep it short and plain.
    """


class SheetsCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.prompt = PROMPT_FILE.read_text(encoding="utf-8")
        self.ask_prompt = ASK_PROMPT_FILE.read_text(encoding="utf-8")
        self.gemini = genai.Client(api_key=os.environ["gemkey"])
        self._rows = None
        self._rows_at = 0.0

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        self.sheets = build(
            "sheets", "v4", credentials=credentials, cache_discovery=False
        )
        if bot is not None:
            self.expire_rows.start()

    def cog_unload(self):
        self.expire_rows.cancel()

    # --- expiry ---

    @tasks.loop(hours=24)
    async def expire_rows(self):
        try:
            removed = await asyncio.to_thread(expiry.purge, self.sheets, SPREADSHEET_ID)
        except Exception:
            log.exception("Expiry sweep failed")
            return
        log.info("Expiry sweep removed %d row(s)", len(removed))

    @expire_rows.before_loop
    async def wait_for_bot(self):
        await self.bot.wait_until_ready()

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
    def build_contents(link, embed, posting):
        today = datetime.date.today().strftime("%B %d, %Y")
        contents = f"Today is {today}. Extract the opportunity at this URL: {link}"
        if posting:
            contents += (
                f"\n\nFull posting, fetched from the {posting['system']} API "
                f"(treat this as the page - do not fetch the URL):"
                f"\n  Title: {posting['title']}"
                f"\n  Location: {posting['location']}"
                f"\n  Description: {posting['text']}"
            )
        if embed:
            contents += "\n\nDiscord's link preview for this URL:"
            for label in ("title", "description", "site"):
                if embed.get(label):
                    contents += f"\n  {label.capitalize()}: {embed[label]}"
        return contents

    def call_gemini(self, contents, config, label):
        for attempt, model in enumerate(MODELS):
            last = attempt == len(MODELS) - 1
            try:
                return self.gemini.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except genai_errors.APIError as error:
                if error.code not in RETRY_CODES or last:
                    raise
                log.warning("Gemini %s from %s for %s", error.code, model, label)
                # 429 is a per-minute quota, so it needs a longer wait than a 503 spike.
                time.sleep(20 if error.code == 429 else 2)

    def generate(self, link, embed, posting):
        contents = self.build_contents(link, embed, posting)
        # With the posting already in hand there is nothing to fetch, and leaving the
        # tool off avoids the 503-prone tool call entirely.
        config = types.GenerateContentConfig(
            system_instruction=self.prompt,
            tools=None if posting else [types.Tool(url_context=types.UrlContext())],
            response_mime_type="application/json",
            response_schema=Opportunity,
        )
        return self.call_gemini(contents, config, link)

    def extract(self, link, embed=None):
        posting = ats.resolve(link)
        try:
            response = self.generate(link, embed, posting)
        except Exception as error:
            log.exception("Gemini call failed for %s", link)
            raise ExtractionError("the extractor is unavailable right now") from error

        opportunity = response.parsed
        if opportunity is None:
            log.error("Unparseable response for %s: %s", link, response.text)
            raise ExtractionError("that posting couldn't be read")

        # We know what the model was given, so the source is ours to set when we
        # supplied the posting, and to sanity-check against the fetch metadata otherwise.
        if posting:
            opportunity.source = Source.API
        elif opportunity.source == Source.PAGE and self.retrieval_failed(response):
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
    def word_list(text):
        return re.findall(r"[a-z]+", text.lower())

    @classmethod
    def words(cls, text):
        return set(cls.word_list(text))

    @staticmethod
    def is_name(word):
        # Short words fuzz too easily ("dial" is one edit from "dan"), so only try the
        # near-miss check on words long enough to plausibly be a misspelled name.
        if word in NAME_WORDS:
            return True
        return len(word) >= 5 and bool(
            difflib.get_close_matches(word, NAME_FUZZY, n=1, cutoff=NAME_FUZZY_CUTOFF)
        )

    def mentioned(self, message):
        return bool(self.bot and self.bot.user in message.mentions)

    def addressed(self, message):
        return self.mentioned(message) or any(
            self.is_name(word) for word in self.word_list(message.content)
        )

    def directed(self, message):
        """Named up front and shaped like a request - the gate for the query path."""
        words = self.word_list(message.content)
        mentioned = self.mentioned(message)
        # An @mention isn't captured as a word but does the job of the leading name.
        if len(words) < MIN_QUERY_WORDS - (1 if mentioned else 0):
            return False
        if not (mentioned or any(map(self.is_name, words[:NAME_LEAD_WORDS]))):
            return False
        return message.content.rstrip().endswith("?") or bool(set(words) & REQUEST_CUES)

    @classmethod
    def reply_for(cls, content, username):
        words = cls.words(content)
        lowered = content.lower()
        short = len(cls.word_list(content)) <= SHORT_MESSAGE
        if words & HELP_WORDS or any(phrase in lowered for phrase in HELP_PHRASES):
            return HELP_TEXT
        if words & SHEET_WORDS and (short or words & LINK_REQUEST_WORDS):
            return f"Here you go {username}: {SHEET_LINK}"
        if words & INTERN_WORDS and short and not words & QUESTION_CUES:
            return "Yes, ALL of you are getting internships and are going to become rich!"
        return QUERY

    # --- questions about the sheet ---

    def all_rows(self):
        if self._rows is None or time.monotonic() - self._rows_at > ROWS_CACHE_SECONDS:
            self._rows = (
                self.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=APPEND_RANGE)
                .execute()
                .get("values", [])
            )
            self._rows_at = time.monotonic()
        return self._rows

    @staticmethod
    def display_link(link):
        # Tracking params add hundreds of characters per link and mean nothing to a reader.
        parts = urlparse(link)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if not key.lower().startswith(("utm_", "fbclid", "gclid", "iieid", "gh_src"))
        ]
        return urlunparse(parts._replace(query=urlencode(query)))

    @classmethod
    def compact(cls, rows):
        lines = []
        for row in rows:
            cells = [c.strip() if isinstance(c, str) else "" for c in row] + [""] * 9
            name, role, kind, summary, opens, closes, _, added, link = cells[:9]
            if not name:
                continue
            if len(summary) > SUMMARY_PREVIEW:
                summary = summary[:SUMMARY_PREVIEW].rsplit(" ", 1)[0] + "…"
            lines.append(
                f"- {name} | {role} | {kind} | added: {added} | opens: {opens} | "
                f"closes: {closes} | {cls.display_link(link)}\n  {summary}"
            )
        return "\n".join(lines)

    def ask(self, question, username):
        rows = self.all_rows()
        today = datetime.date.today().strftime("%B %d, %Y")
        contents = (
            f"Today is {today}. {username} says: {question}\n\n"
            f"The sheet has {len(rows)} rows:\n\n{self.compact(rows)}"
        )
        config = types.GenerateContentConfig(system_instruction=self.ask_prompt)
        try:
            response = self.call_gemini(contents, config, f"question from {username}")
        except Exception as error:
            log.exception("Gemini call failed for question from %s", username)
            raise ExtractionError("can't reach my brain right now, try again in a minute") from error
        text = (response.text or "").strip()
        log.info("Answered %s (%d chars): %s", username, len(text), question)
        return None if text == NO_REPLY or not text else text

    @staticmethod
    async def send_long(message, text):
        chunks, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > DISCORD_LIMIT and current:
                chunks.append(current)
                current = ""
            current += line + "\n"
        chunks.append(current)
        for index, chunk in enumerate(chunks):
            if index == 0:
                await message.reply(chunk.rstrip())
            else:
                await message.channel.send(chunk.rstrip())

    async def answer(self, message, question, username):
        async with message.channel.typing():
            try:
                text = await asyncio.to_thread(self.ask, question, username)
            except ExtractionError as error:
                await message.reply(str(error).capitalize())
                return
        if text:
            await self.send_long(message, text)

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
        if reply is QUERY:
            if self.directed(message):
                await self.answer(message, content, username)
        elif reply:
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
