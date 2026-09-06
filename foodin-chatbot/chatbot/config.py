import os
from pathlib import Path

# Project root is two levels up from this file (chatbot/config.py -> chatbot/ -> foodin-chatbot/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    # Load .env from the project root
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

GROQ_API_KEY          = os.getenv("GROQ_API_KEY")
GROQ_MODEL            = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
USE_GROQ              = os.getenv("USE_GROQ", "true").strip().lower() not in {"0", "false", "no", "off"}
GROQ_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "data" / "groq_system_prompt.txt"

DB_CONFIG = {
    'user':       os.getenv('DB_USER',  'root'),
    'password':   os.getenv('DB_PASS',  'harshit@123'),
    'host':       os.getenv('DB_HOST',  '127.0.0.1'),
    'database':   os.getenv('DB_NAME',  'college_practice'),
    'port':       int(os.getenv('DB_PORT', '3306')),
    'autocommit': False,
}
