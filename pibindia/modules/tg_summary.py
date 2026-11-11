import json
import os
import time
from pathlib import Path
import requests
import re

import pibindia.spiders.config as config

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Set in the environment (locally: `source .secrets`; in GitHub Actions: a repo secret)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """
Summarize ONLY the provided PIB press release text.

🎯 Guidelines:
- Write for UPSC and other competitive exams.
- Keep it very precise and concise, factual, and to the point.
- Ignore all external links, references, or other PIB releases.
- DO NOT include unrelated or speculative information.
- Focus strictly on the provided text content.

🧾 Format for Telegram:
• Use bullet points (•)
• Include relevant emojis in every post for readability (📅🏛️📊👥💡📈)
• Highlight key facts, dates, numbers, names, schemes, and ministries.
• Avoid repetition or unnecessary words.
• Maintain neutral, official tone.

Output must be short, very precise, and ready to post.

Text:
{text}
"""


def escape_md(text):
    return re.sub(r"([_*\[\]()~`>#+\\-=|{}.!])", r"\\\1", text)


def clean_text(text):
    return re.sub(r"(Click here.*|For more information.*)", "", text, flags=re.I)


class GeminiQuotaExhausted(Exception):
    """Every model in config.GEMINI_MODELS has used up its daily free limit."""


# ---- model fallback ---------------------------------------------------------
# Each model has its own free quota. We use the first model in config.GEMINI_MODELS
# that is not "blocked". A 429 tells us which limit was hit and how long to wait:
#   per-day limit    -> model blocked for many hours (until Google's daily reset)
#   per-minute limit -> model blocked for a few seconds; the next model is used meanwhile
# Blocks are saved in config.GEMINI_QUOTA_FILE, so the next date's run (a new process)
# does not waste requests on a model that is already used up.

MINUTE_LIMIT_MAX_WAIT = 60  # a block shorter than this is a per-minute limit: worth waiting for
_dead_models = set()  # unknown / unusable models, for this process only


def _quota_file():
    return Path(config.GEMINI_QUOTA_FILE).expanduser()


def _load_blocks():
    try:
        return json.loads(_quota_file().read_text())
    except (OSError, ValueError):
        return {}


def _block(models, seconds, reason):
    blocks = _load_blocks()
    until = time.time() + seconds
    for m in models:
        blocks[m] = {"until": until, "reason": reason}
    now = time.time()
    blocks = {m: b for m, b in blocks.items() if b["until"] > now}  # drop expired
    path = _quota_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blocks, indent=1))


def _parse_429(res):
    """Return (is_daily_limit, wait_seconds, quota_model) from a 429 response."""
    daily, wait, quota_model = False, 60.0, None
    try:
        details = res.json()["error"].get("details", [])
    except (ValueError, KeyError, AttributeError):
        return daily, wait, quota_model
    for d in details:
        kind = d.get("@type", "")
        if kind.endswith("RetryInfo"):
            m = re.match(r"([\d.]+)s", d.get("retryDelay", ""))
            if m:
                wait = float(m.group(1))
        elif kind.endswith("QuotaFailure"):
            for v in d.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    daily = True
                # aliases share quota, e.g. gemini-3.5-flash is counted as gemini-3.6-flash
                quota_model = v.get("quotaDimensions", {}).get("model") or quota_model
    if daily:
        wait = max(wait, 3600)
    return daily, wait, quota_model


def _pick_model():
    """First usable model, or (None, seconds until the earliest short block ends)."""
    blocks = _load_blocks()
    now = time.time()
    soonest = None
    for m in config.GEMINI_MODELS:
        if m in _dead_models:
            continue
        until = blocks.get(m, {}).get("until", 0)
        if until <= now:
            return m, 0
        if until - now <= MINUTE_LIMIT_MAX_WAIT:
            soonest = min(soonest or until - now, until - now)
    return None, soonest


def gemini_generate(prompt):
    """Send one prompt to Gemini and return the reply text.

    Returns "" if this prompt cannot be answered (blocked by safety filters, bad request).
    Raises GeminiQuotaExhausted when no model has free quota left today.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set (run `source .secrets` first)")

    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    server_errors = {}

    for _ in range(4 * len(config.GEMINI_MODELS) + 10):
        model, wait = _pick_model()
        if model is None:
            if wait is None:
                raise GeminiQuotaExhausted(
                    "Gemini quota exhausted: every model has used its daily free limit"
                )
            print(f"Gemini: every model is busy or at its per-minute limit, waiting {wait:.0f}s")
            time.sleep(wait + 1)
            continue

        try:
            res = requests.post(GEMINI_URL.format(model=model), headers=headers,
                                json=body, timeout=60)
        except requests.exceptions.RequestException as e:
            res, err = None, str(e)

        if res is not None and res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates") or []
            if not candidates:
                print(f"Gemini {model} returned no answer: {data.get('promptFeedback')}")
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            print(f"Gemini {model}: ok")
            return text

        if res is not None and res.status_code == 429:
            daily, wait, quota_model = _parse_429(res)
            kind = "daily" if daily else "per-minute"
            print(f"Gemini {model}: {kind} limit reached, trying next model")
            _block({model, quota_model} - {None}, wait, kind)
            continue

        if res is not None and res.status_code == 404:  # model renamed or retired
            print(f"Gemini {model}: not available ({res.status_code}), skipping it")
            _dead_models.add(model)
            continue

        if res is None or res.status_code >= 500:
            # network trouble or Google overloaded: retry, after 2 failures rest the model
            server_errors[model] = server_errors.get(model, 0) + 1
            detail = err if res is None else f"error {res.status_code}"
            print(f"Gemini {model}: {detail}")
            if server_errors[model] >= 2:
                _block([model], 60, "server errors")
                server_errors[model] = 0
            time.sleep(2)
            continue

        print(f"Gemini {model} error {res.status_code}: {res.text[:300]}")
        return ""

    print("Gemini failed after many attempts")
    return ""


def summarize_text(text):
    # Gemini takes ~1M tokens of input, so a press release never needs chunking
    text = clean_text(text)
    print(f"Summarizing ({len(text)} chars)")
    return gemini_generate(PROMPT.format(text=text))


def post_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    safe_message = escape_md(message)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": safe_message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    for attempt in range(3):
        res = requests.post(url, data=payload)
        if res.status_code == 200:
            print("Summary sent successfully!")
            return True
        else:
            print(f"Telegram Error (Attempt {attempt+1}): {res.text}")
    return False
