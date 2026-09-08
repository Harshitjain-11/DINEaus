# chatbot/utils.py
import re

def is_yes(text: str) -> bool:
    t = text.strip()
    if t in ("👍", "👌", "✅", "💯"): return True
    return bool(re.search(
        r"\b(yes+|y|yeah+|yep|yup|ok|okay|sure|confirm|haan+|han|ha|bilkul|"
        r"theek hai|theek|done|absolutely|of course|go ahead|let'?s do it|"
        r"perfect|definitely|zaroor|pakka|sahi|ji|ji haan|approved|chalo)\b",
        text, flags=re.I,
    ))

def is_no(text: str) -> bool:
    t = text.lower().strip()
    if re.search(r"\bno\s*(problem|worries|doubt|issue|probs)\b", t, flags=re.I):
        return False
    return bool(re.search(
        r"\b(no+|n|nope|nah+|nahin|nahi|mat|nai|nahii+)\b",
        text, flags=re.I,
    ))

def safe_numeric_user_id(user_id):
    if not user_id or user_id in ("anonymous", ""): return 1
    try: return int(user_id)
    except: return 1
