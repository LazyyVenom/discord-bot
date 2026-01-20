from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    token = os.getenv("DISCORD_TOKEN")
    db_url = os.getenv("DB_URL", "sqlite:///app.db")
    logging_level = os.getenv("LOGGING_LEVEL", "INFO")