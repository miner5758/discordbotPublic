import discord
import os
import random
from dotenv import load_dotenv
import re
#import google.generativeai as genai | if you are using linux
from google import genai # if you are using windows
from google.genai import types
import os.path
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# If modifying these scopes, delete the file token.json.
# IMPORTANT: Changed scope to allow writing to spreadsheets.
# You MUST delete your existing 'token.json' file for this change to take effect.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# The ID of your spreadsheet.
# Renamed from SAMPLE_SPREADSHEET_ID
SPREADSHEET_ID = "1oXxHr3n1uGL2ZPcMDFiVFUQKASmQ4k5WMTlbJhrbCbI"
# The range where data will be appended.
# Renamed from SAMPLE_RANGE_NAME
RANGE_NAME = "A2:E"

url_pattern = re.compile(
        r'https?://[^\s/$.?#].[^\s]*'  # Matches http:// or https:// followed by non-whitespace
        r'|www\.[^\s/$.?#].[^\s]*'     # Matches www. followed by non-whitespace
        r'|[a-zA-Z0-9]+\.[a-zA-Z0-9]+\.[a-zA-Z]{2,}' # Matches domain.tld or sub.domain.tld
    )

def sheetsedit(dataa):
    """Appends a row of data to a Google Sheet."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        service = build("sheets", "v4", credentials=creds)

        # The data to append, converted from the dictionary to a list of lists.
        # Each inner list represents a row.
        data_to_append = [
            dataa
        ]

        body = {
            "values": data_to_append
        }

        # Call the Sheets API to append the data
        sheet = service.spreadsheets()
        result = (
            sheet.values()
            .append(
                spreadsheetId=SPREADSHEET_ID, # Updated variable name
                range=RANGE_NAME,             # Updated variable name
                valueInputOption="USER_ENTERED", # How the input data should be interpreted.
                body=body
            )
            .execute()
        )
        #print(f"{result.get('updates').get('updatedCells')} cells appended.")
        #print("Data successfully appended to the sheet!")
        return True

    except HttpError as err:
        #print(f"An error occurred: {err}")
        return False





def gemreasoning(linkk):
    gemkey = os.getenv('gemkey')
    genai.configure(api_key=gemkey) # Configure the API key directly
    
    # Use genai.upload_file instead of client.files.upload
    my_file = genai.upload_file('gem.md')

    # Wait for the file to be active
    while my_file.state.name == "PROCESSING":
        # Optional: Add a small delay to avoid busy-waiting
        import time
        time.sleep(1)
        my_file = genai.get_file(my_file.name)


    response = genai.GenerativeModel(
        model_name="gemini-2.5-pro" 
    ).generate_content(
        contents=[my_file, f"read the instutions in the markdown file. Then, use this link: {linkk}"],
    )
    ourinfolist = response.text.split(",")
    #print("next")
    success = sheetsedit(ourinfolist)
    return success

def is_link(text):
    # This regex attempts to match common URL patterns.
    # It covers:
    # 1. http:// or https:// followed by any characters (non-whitespace)
    # 2. www. followed by any characters (non-whitespace)
    # 3. A word character sequence followed by a dot, then another word character
    #    sequence, and at least one more dot and a TLD (e.g., example.com, sub.domain.org)
    #    This last part is a bit more permissive to catch simple domain names.
    

    # Search for the pattern in the given text
    if url_pattern.search(text):
        return True
    else:
        return False
    



def extract_link(text):
    
    match = re.search(url_pattern, text)
    if match:
        return match.group()
    else:
        return None










load_dotenv("file.env") # Load environment variables from file.env. Removed from project for security reasons.
# Ensure the environment variable 'discordtok' and 'gemtok' is set in your .env file with your token's.

token = os.getenv('discordtok')
intents = discord.Intents.default()
intents.message_content = True # Explicitly enable message content intent
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print("Logged in as a bot {0.user}".format(client))
    
    


@client.event
async def on_message(message):
    username = str(message.author).split("#")[0]
    channel = str(message.channel.name)
    user_message = str(message.content)

    #print(f'Message {user_message} by {username} on {channel}')
    

    if message.author == client.user:
        return
    
    if channel == 'please':
        if is_link(user_message.lower()):
            await message.channel.send(f'adding link from {username} to the sheet...')
            uselink = extract_link(user_message.lower())
            decide = False
            try:
                decide = gemreasoning(uselink)
            except Exception as e:
                await message.channel.send(e)
                return
            
            if decide:
                await message.channel.send(f"Successfully added link from {username} to the sheet!")
            else:
                await message.channel.send(f"Failed to add link from {username} to the sheet. Please try again later.")

        if user_message.lower() == "ryan roslansky give me the link to the spreadsheet":
            await message.channel.send(f"Here you go {username}: https://docs.google.com/spreadsheets/d/1oXxHr3n1uGL2ZPcMDFiVFUQKASmQ4k5WMTlbJhrbCbI/edit?usp=sharing")
        elif user_message.lower() == "ryan roslansky are we getting internships?":
            await message.channel.send("Yes, ALL of you are getting internships and are going to become rich!")

client.run(token)