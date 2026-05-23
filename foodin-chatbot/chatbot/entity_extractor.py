# chatbot/entity_extractor.py
"""
Hybrid entity extractor — Fixed Version
- Uses spaCy (if installed) for noun chunks and POS
- Falls back to regex-based extraction
- Added Hinglish support: "4 log", "kal", "aaj", "7 baje", "char log"
- Fixed people regex: now catches "4 people", "4 log", "table for 2"
- Fixed time regex: now catches "7pm", "8:30pm", "7 baje" (not just "at 7pm")
- Fixed date: "kal", "aaj", "parso" support added

Provides:
- extract_order_id(text)
- extract_quantity(text)
- extract_items(text, menu=None) -> list of {"name":..., "qty":...}
- extract_booking(text) -> {"people":int, "time":"HH:MM", "date":"YYYY-MM-DD", "preference":str}
- normalize_number_word(word) -> int or None
- fuzzy_match_item(name, menu) -> best match
"""

import re
from datetime import date, timedelta
from difflib import get_close_matches

# ── spaCy (optional) ──────────────────────────────────────────────────────────
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    # To use heavier model: python -m spacy download en_core_web_md
    # then replace "en_core_web_sm" with "en_core_web_md"
except Exception:
    _nlp = None

# ── Number word mappings (English + Hinglish) ─────────────────────────────────
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a": 1, "an": 1,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10
}

_NUM_WORDS_PATTERN = '|'.join(sorted(_NUM_WORDS.keys(), key=len, reverse=True))

# ── Regex patterns ────────────────────────────────────────────────────────────

# PEOPLE — catches: "for 4", "table for 2", "4 people", "4 log",
#                   "char log", "two people", "4 guests", "4 of us"
_people_patterns = [
    re.compile(
        rf'\b(?:for|table\s+for|reserve\s+for|book\s+for|seats?\s+for)\s+(\d{{1,2}}|{_NUM_WORDS_PATTERN})\b',
        re.I
    ),
    re.compile(
        rf'\b(\d{{1,2}}|{_NUM_WORDS_PATTERN})\s+(?:people|persons?|guests?|log|members?|friends?|of\s+us|ke\s+liye|logo?\s+ke\s+liye)\b',
        re.I
    ),
    re.compile(
        rf'^\s*(\d{{1,2}}|{_NUM_WORDS_PATTERN})\s*$',
        re.I
    ),
]

# TIME — catches: "7pm", "8:30pm", "8:30 pm", "at 7pm", "@ 8pm"
_time_regex = re.compile(
    r'(?:at|@)?\s*(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)',
    re.I
)

# TIME 24h — catches "20:30"
_time_24h_regex = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b')

# TIME Hinglish — catches "7 baje", "saat baje"
_time_hinglish_regex = re.compile(
    rf'\b(\d{{1,2}}|{_NUM_WORDS_PATTERN})\s+baje\b',
    re.I
)

# ITEM QTY
_qty_item_regex = re.compile(
    rf'\b(\d+|{_NUM_WORDS_PATTERN})\b\s*(?:x|pcs|pieces|of)?\s*([A-Za-z &]+?)\b(?:,|\s+and\s+|$|\.)',
    re.I
)


def normalize_number_word(w):
    """Convert word or digit string to int. Returns None if not recognizable."""
    if w is None:
        return None
    try:
        return int(w)
    except (ValueError, TypeError):
        return _NUM_WORDS.get(str(w).lower().strip())


def extract_order_id(text):
    """Extract a numeric order ID from text."""
    if not text:
        return None
    m = re.search(r'\b(\d{1,8})\b', text)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def extract_quantity(text):
    """Extract first quantity from text."""
    if not text:
        return None
    m = re.search(r'\b(\d+)\b', text)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, TypeError):
            pass
    for word, val in _NUM_WORDS.items():
        if re.search(r'\b' + re.escape(word) + r'\b', text, flags=re.I):
            return val
    return None


def fuzzy_match_item(name, menu=None):
    """
    If menu provided, return best fuzzy match via difflib.
    Else return normalized name.
    """
    name = name.strip().lower()
    if not menu:
        return name
    choices = [m.lower() for m in menu]
    if name in choices:
        return name
    matches = get_close_matches(name, choices, n=1, cutoff=0.6)
    return matches[0] if matches else name


def extract_booking(text):
    """
    Extract booking info from natural language (English + Hinglish).

    Returns:
        {
            "people":     int or None,
            "time":       "HH:MM" or None,
            "date":       "YYYY-MM-DD" or None,
            "preference": str or None
        }

    Examples handled:
        "table for 4 at 7pm tomorrow"
        "bhai 4 log kal 8 baje window seat"
        "reserve for 2 today at 8:30pm"
        "char log aaj raat 7 baje"
        "2 people tonight"
    """
    if not text:
        return {}

    people     = None
    tm         = None
    dt         = None
    preference = None
    text_lower = text.lower()

    # ── PEOPLE ────────────────────────────────────────────────────────────────
    for pattern in _people_patterns:
        m = pattern.search(text)
        if m:
            val = normalize_number_word(m.group(1))
            if val and 1 <= val <= 50:
                people = val
                break

    # ── TIME ──────────────────────────────────────────────────────────────────
    # 1. Hinglish "7 baje" / "saat baje"
    m = _time_hinglish_regex.search(text)
    if m:
        raw = m.group(1)
        hh  = normalize_number_word(raw)
        if hh and 1 <= hh <= 12:
            hh += 12  # assume PM for restaurant hours
            tm = f"{hh:02d}:00"

    # 2. Standard "7pm", "8:30pm", "at 7pm"
    if not tm:
        m = _time_regex.search(text)
        if m:
            hh   = int(m.group(1))
            mm   = int(m.group(2)) if m.group(2) else 0
            ampm = m.group(3).lower()
            if ampm == "pm" and hh < 12:
                hh += 12
            if ampm == "am" and hh == 12:
                hh = 0
            if 0 <= hh <= 23:
                tm = f"{hh:02d}:{mm:02d}"

    # 3. 24-hour "20:30"
    if not tm:
        m = _time_24h_regex.search(text)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            if 10 <= hh <= 23:
                tm = f"{hh:02d}:{mm:02d}"

    # ── DATE ──────────────────────────────────────────────────────────────────
    # Hinglish + English keywords
    if re.search(r'\bparso\b|\bday\s+after\s+tomorrow\b', text_lower):
        dt = (date.today() + timedelta(days=2)).isoformat()
    elif re.search(r'\bkal\b|\btomorrow\b|\btmrw\b|\btmr\b', text_lower):
        dt = (date.today() + timedelta(days=1)).isoformat()
    elif re.search(r'\baaj\b|\btoday\b|\btonight\b|\baaj\s+raat\b', text_lower):
        dt = date.today().isoformat()

    # Explicit ISO date: 2024-12-31
    if not dt:
        m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
        if m:
            dt = m.group(1)

    # DD/MM or DD-MM
    if not dt:
        m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})\b', text)
        if m:
            try:
                day   = int(m.group(1))
                month = int(m.group(2))
                dt    = f"{date.today().year}-{month:02d}-{day:02d}"
            except (ValueError, TypeError):
                pass

    # Month name + day: "15 june", "june 15", "15th june"
    if not dt:
        _MONTHS = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        for mname, mnum in _MONTHS.items():
            m = re.search(
                rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{mname}\b'
                rf'|\b{mname}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b',
                text_lower
            )
            if m:
                try:
                    day = int(m.group(1) or m.group(2))
                    dt  = f"{date.today().year}-{mnum:02d}-{day:02d}"
                    break
                except (ValueError, TypeError):
                    pass

    # ── PREFERENCE / SEAT TYPE ────────────────────────────────────────────────
    pref_m = re.search(
        r'\b(window|near\s+window|outdoor|outside|inside|indoor|corner|rooftop|private)\b',
        text, flags=re.I
    )
    if pref_m:
        preference = pref_m.group(1).lower().replace(' ', '_')

    return {
        "people":     people,
        "time":       tm,
        "date":       dt,
        "preference": preference
    }


# ── Item Extraction ───────────────────────────────────────────────────────────

def _regex_extract_items(text):
    """Regex-based item extraction fallback."""
    items = []
    for m in _qty_item_regex.finditer(text + " "):
        qty_raw  = m.group(1)
        qty      = normalize_number_word(qty_raw)
        item_raw = m.group(2).strip()
        if item_raw:
            items.append({"name": item_raw, "qty": qty or 1})

    if not items:
        parts = re.split(r',|\s+and\s+', text)
        for p in parts:
            p  = p.strip()
            q  = extract_quantity(p)
            p2 = re.sub(rf'\b({_NUM_WORDS_PATTERN}|\d+)\b', '', p, flags=re.I).strip()
            p2 = re.sub(
                r'\b(order|add|want|take|get|i would like|i\'ll take|i want|'
                r'chahiye|de do|lena|mangwa|dena|bhejdo)\b',
                '', p2, flags=re.I
            ).strip()
            if p2:
                items.append({"name": p2, "qty": q or 1})
    return items


def extract_items(text, menu=None):
    """
    Returns list of {"name":..., "qty":...}
    menu (optional): list of valid menu item names for fuzzy matching
    """
    if not text:
        return []

    # ── spaCy path ────────────────────────────────────────────────────────────
    if _nlp:
        doc   = _nlp(text)
        items = []

        for ent in doc.ents:
            if ent.label_ in ("CARDINAL", "QUANTITY", "NUMBER"):
                start = ent.end
                if start < len(doc):
                    noun = None
                    for token in doc[start:start + 4]:
                        if token.pos_ in ("NOUN", "PROPN"):
                            noun = token.text
                            break
                    if noun:
                        qty = normalize_number_word(ent.text)
                        items.append({"name": noun, "qty": qty or 1})

        if not items:
            for chunk in doc.noun_chunks:
                txt = chunk.text.strip()
                if (len(txt.split()) <= 4 and
                        not re.search(r'\b(table|order|time|people|book|log)\b', txt, flags=re.I)):
                    qty = 1
                    i   = chunk.start
                    if i - 1 >= 0 and doc[i - 1].like_num:
                        qty = normalize_number_word(doc[i - 1].text) or 1
                    items.append({"name": txt, "qty": qty})

        cleaned = []
        for it in items:
            nm      = re.sub(r'[^\w\s&-]', '', it["name"].lower()).strip()
            matched = fuzzy_match_item(nm, menu)
            cleaned.append({"name": matched, "qty": int(it.get("qty", 1) or 1)})
        return cleaned

    # ── Regex fallback ────────────────────────────────────────────────────────
    found   = _regex_extract_items(text)
    cleaned = []
    for it in found:
        nm      = re.sub(r'[^\w\s&-]', '', it["name"].lower()).strip()
        matched = fuzzy_match_item(nm, menu)
        cleaned.append({"name": matched, "qty": int(it.get("qty", 1) or 1)})
    return cleaned