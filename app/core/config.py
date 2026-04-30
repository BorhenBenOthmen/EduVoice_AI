import os
from dotenv import load_dotenv

load_dotenv()

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY_FALLBACK = os.getenv("GEMINI_API_KEY_FALLBACK")

# Model supporting live streaming
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-live-preview")
MODEL_NAME_FALLBACK = os.getenv("MODEL_NAME_FALLBACK", "gemini-2.5-flash")

# Django backend URL for fetching app content (lessons, podcasts, etc.)
DJANGO_BACKEND_URL = os.getenv("DJANGO_BACKEND_URL", "https://radio.backend.ecocloud.tn/ai/get_lessons_list")

if not GEMINI_API_KEY or not GEMINI_API_KEY.startswith("AIza"):
    import sys
    print("CRITICAL ERROR: Invalid GEMINI_API_KEY in .env file.")
    sys.exit(1)
