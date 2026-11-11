# config file

PIB_BASE_DIR = "~/pib"
PIB_ARTICLES_DIR = "~/pib/articles"
PIB_LINKS_DIR = "~/pib/article_links"
PIB_TEXT_DIR = "~/pib/article_text"
PIB_JSON_DIR = "~/pib/json_dir"
PIB_SUMMARY_DIR = "~/pib/summaries"

# PIB main site defaults to Hindi without these params (reg=3 Delhi HQ, lang=1 English)
PIB_LISTING_URL = "https://pib.gov.in/AllRelease.aspx?reg=3&lang=1"

# Feature switches (temporarily off while testing)
ENABLE_TELEGRAM = False  # LLM summary + Telegram post
ENABLE_PDF_DOWNLOAD = False  # pdfkit download of each article
ENABLE_DAILY_SUMMARY = True  # one summary file per date: ~/pib/summaries/<dd_Mmm_yyyy>.txt

# Gemini models for summaries, tried in this order (API key comes from GEMINI_API_KEY).
# When one hits its free-tier limit the next one is used. Free limits per day (Nov 2026):
GEMINI_MODELS = [
    "gemini-3.8-flash",        # 20/day, 5/min
    "gemini-3.6-flash",        # 20/day, 5/min (gemini-3.5-flash shares this quota)
    "gemini-3-flash-preview",  # 20/day, 5/min
    "gemini-2.5-flash",        # 20/day, 5/min
    "gemini-3.5-flash-lite",   # 500/day, 15/min
    "gemini-2.5-flash-lite",   # 20/day, 10/min
]
# Remembers which models are used up until when, shared by all runs
GEMINI_QUOTA_FILE = "~/pib/gemini_quota.json"
