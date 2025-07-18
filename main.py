from core_bot import start_discord_bot
from dotenv import load_dotenv

load_dotenv(dotenv_path="/home/azureuser/discordbot/discordbotpublic/resources/file.env",override=True)  # Load Discord and Gemini tokens

if __name__ == "__main__":
    start_discord_bot()