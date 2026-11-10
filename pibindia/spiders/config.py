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

# Gemini model used for summaries (API key comes from the GEMINI_API_KEY env variable)
GEMINI_MODEL = "gemini-3.5-flash"
