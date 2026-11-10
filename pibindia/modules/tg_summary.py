import os
import time
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


def gemini_generate(prompt, retries=5):
    """Send one prompt to Gemini and return the reply text ("" if it fails)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set (run `source .secrets` first)")

    url = GEMINI_URL.format(model=config.GEMINI_MODEL)
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }

    for attempt in range(1, retries + 1):
        try:
            res = requests.post(url, headers=headers, json=body, timeout=120)
        except requests.exceptions.RequestException as e:
            print(f"Gemini request failed (attempt {attempt}/{retries}): {e}")
            time.sleep(2**attempt)
            continue

        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates") or []
            if not candidates:
                print(f"Gemini returned no answer: {data.get('promptFeedback')}")
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip()

        # 429 = rate limit, 5xx = server problem: wait and retry. Anything else: give up.
        if res.status_code == 429 or res.status_code >= 500:
            wait = 2**attempt * 5 if res.status_code == 429 else 2**attempt
            print(f"Gemini error {res.status_code} (attempt {attempt}/{retries}), retrying in {wait}s")
            time.sleep(wait)
            continue

        print(f"Gemini error {res.status_code}: {res.text[:300]}")
        return ""

    print(f"Gemini failed after {retries} attempts")
    return ""


def summarize_text(text):
    # Gemini takes ~1M tokens of input, so a press release never needs chunking
    text = clean_text(text)
    print(f"Summarizing with {config.GEMINI_MODEL} ({len(text)} chars)")
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
