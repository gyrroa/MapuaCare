# app/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root (one level above app/)
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env explicitly; then fall back to .env.example if needed
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "CARE Backend")
    VERSION: str = os.getenv("VERSION", "1.3.0")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./care.db")

    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        if DEBUG:
            SECRET_KEY = "dev-only-change-me-please"
        else:
            raise RuntimeError("SECRET_KEY is required. Put it in a .env file.")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

settings = Settings()
