# Opportunities Discord Bot

A Discord bot that watches an `#opportunities` channel for job and internship links,
reads each posting with Gemini, and appends a structured row to a Google Sheet.

Post a link, get a row. The bot reacts ⏳ while it works, then ✅ when the row lands.

---

## How it works

1. Someone posts a link in `#opportunities`.
2. The bot checks the sheet and skips links that are already there, and waits a
   moment for Discord to attach its link preview to the message.
3. If the link is hosted on Greenhouse, Ashby, or Lever, the bot pulls the full
   posting from that system's public API — see [`src/ats.py`](src/ats.py). Those
   careers pages are JavaScript shells that block fetchers, but the API behind them
   is open.
4. Gemini gets the URL, the preview, and either the API posting or a fetch of the page
   via the `url_context` tool, then returns a filled-in `Opportunity` object. The
   shape is enforced by the API's response schema, not by asking the model nicely —
   see [`src/models.py`](src/models.py).
5. The row is appended to the sheet.

The model uses the richest source it has, in this order:

| Source | When | What you get |
|---|---|---|
| api | the link is on Greenhouse, Ashby, or Lever | full posting, pay and dates if stated |
| page | the fetch worked | full summary, dates if stated |
| embed | page blocked, Discord's preview exists | title, role, short summary |
| url | no page, no preview, but the URL spells out the role | name and role from the slug |
| none | nothing usable | a `Needs review` row with just the link |

Discord's preview matters because it comes from a different fetcher than Gemini's —
job sites deliberately allow it so that social sharing works, so it often succeeds
where the page fetch is blocked. Which source each row came from is in the service
log (`journalctl -u discordbot`).

If the Gemini API itself is down or rate limited, nothing is written, because retrying
later would have worked.

### Sheet columns

```
A Name | B Role Type | C Opportunity Type | D Summary | E Open Date | F Close Date | G Posted By | H Date Added | I Link
```

`Role Type` and `Opportunity Type` are fixed enums defined in
[`src/models.py`](src/models.py). Keeping them constrained is what makes the columns
filterable; if you add a value there, it applies to new rows only.

---

## Setup

Requires Python 3.13. Python 3.14 works but has thinner wheel coverage.

### 1. Install

```powershell
git clone https://github.com/miner5758/discordbotPublic.git
cd discordbotPublic
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On Linux, substitute `python3 -m venv .venv` and `.venv/bin/python`.

### 2. Google service account

The bot writes to the sheet as a service account, so there is no browser consent flow
and no token to expire.

1. Open the [service accounts page](https://console.cloud.google.com/iam-admin/serviceaccounts)
   for your Cloud project and create one. Skip the "grant access to project" step —
   project roles are not what grants sheet access.
2. Open it, go to **Keys** → **Add key** → **Create new key** → **JSON**.
3. Save the downloaded file as `src/service_account.json`.
4. Copy the service account's email (it ends in `.iam.gserviceaccount.com`), then open
   the spreadsheet → **Share** → paste the email → **Editor**.

Step 4 is the one people forget. A service account is its own identity; until the sheet
is shared with it, every write returns 403.

Make sure the [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
is enabled for the project.

### 3. Discord application

1. At the [Developer Portal](https://discord.com/developers/applications), open your app
   → **Bot** → **Reset Token** and copy it. A token is only shown once.
2. On the same page, enable **MESSAGE CONTENT INTENT** under Privileged Gateway Intents.
   The bot reads message text, so it will not start without this.
3. Invite it with **View Channel**, **Send Messages**, **Read Message History**, and
   **Add Reactions** (permissions integer `68672`):

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=68672&scope=bot
   ```

Without Add Reactions the bot still works, but the ⏳/✅ feedback silently does nothing.

### 4. Credentials file

```powershell
copy src\resources\file.env.example src\resources\file.env
```

Then fill in both values:

```
discordtok=your-discord-bot-token
gemkey=your-gemini-api-key
```

Get a Gemini key from [AI Studio](https://aistudio.google.com/apikey). No quotes, no
spaces around the `=`. This file is gitignored — keep it that way.

> If you have a `gemkey` set as a system environment variable, delete it. Anything that
> loads the env file without `override=True` will silently pick up the stale one.

### 5. Configure the target sheet

Set `SPREADSHEET_ID` and `CHANNEL_NAME` in [`src/sheets_cog.py`](src/sheets_cog.py), then
write the header row:

```powershell
.venv\Scripts\python.exe src\scripts\init_sheet.py
```

This **erases** the sheet, so it prompts before doing anything.

---

## Running

```powershell
.venv\Scripts\python.exe src\main.py
```

It logs `Logged in as <name> (ID: ...)` once connected. The env file is read from
`src/resources/file.env`; set `DOTENV_PATH` to point somewhere else.

---

## Using it

Everything below only works in the channel named by `CHANNEL_NAME` (`opportunities` by
default). Other channels are ignored.

**Post a link** — one or more per message. Links need `https://` or `www.`.

| Reaction | Meaning |
|---|---|
| ⏳ | working |
| ✅ | row added |
| ⚠️ | added, but the page could not be read — fill the row in by hand |
| 🔁 | already in the sheet |
| ❌ | nothing written, try again later |

**Talking to it** — say its name (`dan`, `daniel`, `shapero`, or a close misspelling)
or @mention it, plus one of these, in any order and with any extra words:

| Mention | It replies with |
|---|---|
| `sheet`, `spreadsheet`, `excel` | the spreadsheet link |
| `intern`, `internships`, `offer`, `hired`, `job`, `rich` | morale support |
| `help`, `commands`, `what can you do` | this list |

So `dan spreadsheet?`, `yo shapero where's the sheet`, and `@bot link pls sheet` all
work. Both halves are required: the name alone stays silent, since the bot is named
after a real person who comes up in conversation, and an intent word alone stays
silent so it doesn't answer every casual mention of the sheet.

A message containing a URL always goes to extraction instead, even if it also names
the bot.

Duplicate detection ignores `www.`, trailing slashes, and `utm_*` parameters, so the
same posting shared from LinkedIn or pasted directly counts once. Deleting a row makes
that link eligible again.

---

## Layout

```
src/
  main.py                  entry point, loads the env file
  core_bot.py              client setup, registers the cog in setup_hook
  sheets_cog.py            message handling, Gemini calls, sheet writes
  ats.py                   pulls postings from Greenhouse / Ashby / Lever APIs
  models.py                response schema and the two enums
  resources/gem.md         the extraction prompt
  scripts/init_sheet.py    one-off: wipe the sheet, write headers
  scripts/test_extract.py  run extraction on URLs without Discord
```

---

## Troubleshooting

**Nothing happens when I post a link.** Check the channel's own name matches
`CHANNEL_NAME` exactly. A category named `opportunities` does not count — the bot reads
`message.channel.name`.

**`PrivilegedIntentsRequired` on startup.** Message Content Intent is not enabled in the
Developer Portal.

**403 on every sheet write.** The spreadsheet is not shared with the service account's
email.

**403 `API key was reported as leaked`.** Google detected the key publicly. Rotate it and
check nothing logs it.

**Frequent 429 or 503 from Gemini.** Free-tier quota and capacity spikes. `MODELS` in
[`src/sheets_cog.py`](src/sheets_cog.py) lists models tried in order, moving to the next
one on failure. Reorder it if a particular model is consistently saturated.

To debug extraction without Discord in the way:

```powershell
.venv\Scripts\python.exe src\scripts\test_extract.py https://example.com/some-job
```
