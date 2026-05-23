# chatbot/response_generator.py
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
INTENTS_PATH = DATA_DIR / "intents.json"

def load_intents():
    if not INTENTS_PATH.exists():
        return {}
    with open(INTENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_INTENTS_DATA = load_intents()
_RESPONSES = {item["tag"]: item.get("responses", []) for item in _INTENTS_DATA.get("intents", [])}

def choose_response(tag: str):
    choices = _RESPONSES.get(tag, [])
    if not choices:
        return None
    return random.choice(choices)
