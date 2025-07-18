# sheets_cog.py
import discord
from discord.ext import commands
import re
import os
import time
from google import genai
from google.genai import types
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1oXxHr3n1uGL2ZPcMDFiVFUQKASmQ4k5WMTlbJhrbCbI"
RANGE_NAME = "A2:E"

class SheetsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemkey = os.getenv("gemkey")

    def is_link(self, text: str) -> bool:
        url_pattern = re.compile(
            r'https?://[^\s/$.?#].[^\s]*|www\.[^\s/$.?#].[^\s]*|[a-zA-Z0-9]+\.[a-zA-Z0-9]+\.[a-zA-Z]{2,}'
        )
        return bool(url_pattern.search(text))

    def extract_link(self, text: str) -> str:
        match = re.search(r'(https?://[^\s]+|www\.[^\s]+)', text)
        return match.group() if match else None

    def sheetsedit(self, dataa):
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())

        try:
            service = build("sheets", "v4", credentials=creds)
            body = {"values": [dataa]}
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGE_NAME,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            return True
        except HttpError:
            return False

    def gemreasoning(self, link):
        try:
            genai.configure(api_key=self.gemkey)
            my_file = genai.upload_file("resources/gem.md")

            while my_file.state.name == "PROCESSING":
                time.sleep(1)
                my_file = genai.get_file(my_file.name)

            response = genai.GenerativeModel("gemini-2.5-pro").generate_content(
                contents=[my_file, f"read the instructions in the markdown file. Then, use this link: {link}"]
            )

            ourinfolist = response.text.split(",")
            return self.sheetsedit(ourinfolist)
        except Exception as e:
            print(f"[Gemini Error] {self.gemkey}")
            return False

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        channel_name = str(message.channel.name)
        content = message.content.lower()
        username = str(message.author).split("#")[0]

        if channel_name != "please":
            return

        if content == "ryan roslansky give me the link to the spreadsheet":
            await message.channel.send(
                f"Here you go {username}: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=sharing"
            )
            return
        elif content == "ryan roslansky are we getting internships?":
            await message.channel.send(
                "Yes, ALL of you are getting internships and are going to become rich!"
            )
            return

        if self.is_link(content):
            await message.channel.send(f"adding link from {username} to the sheet...")
            uselink = self.extract_link(content)

            try:
                success = self.gemreasoning(uselink)
                if success:
                    await message.channel.send(f"Successfully added link from {username} to the sheet!")
                else:
                    await message.channel.send(f"Failed to add link from {username} to the sheet.")
            except Exception as e:
                await message.channel.send(f"Error occurred: {e}")
