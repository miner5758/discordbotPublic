import os
from core_bot import start_discord_bot
from dotenv import load_dotenv

# Load Discord and Gemini tokens from resources/file.env next to this script,
# or from the path in DOTENV_PATH if it is set.
ENV_PATH = os.getenv(
    "DOTENV_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "file.env"),
)
load_dotenv(dotenv_path=ENV_PATH, override=True)

if __name__ == "__main__":
    start_discord_bot()
