# pib

Fetch press releases from the [Press Information Bureau, India](https://pib.gov.in) for any date or date range and summarize each release with Google Gemini. Includes a local website, **PIB Depths**, where you pick dates, watch the progress and read the summaries in the browser.

Useful for candidates preparing for UPSC and other government exams.

## Features

- Fetches every English press release published on a date (the PIB site goes back to 2017)
- Saves each article's title, ministry, link and full text as JSON
- Summarizes every article with Gemini into one text file per date
- Local web interface: choose a date range, follow live progress, browse, search and filter summaries by ministry
- Optional (off by default): save each release as a PDF and post summaries to Telegram

## Requirements

- Python 3.12 (a conda environment is recommended)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- `wkhtmltopdf`, only if you turn on PDF downloads

## Setup

```bash
git clone https://github.com/saransh0988/pib
cd pib

conda create -n pib python=3.12
conda activate pib
pip install -r requirements.txt
```

Store your Gemini key in a `.secrets` file in the project folder. It is listed in `.gitignore`, so it is never committed:

```bash
echo 'export GEMINI_API_KEY="your-key-here"' > .secrets
chmod 600 .secrets
```

> Never put keys in `.env`. That file is tracked by git and holds the shell helper functions.

## Using the website

```bash
conda activate pib
cd pib
python webapp/server.py
```

Open **http://127.0.0.1:8000** in your browser. The server reads the Gemini key from `.secrets` by itself. Press `Ctrl+C` in the terminal to stop it.

- **Dive**: pick a start and end date (up to 31 days) and press **DIVE**. Dates that already have a complete summary are skipped unless you tick *Re-summarize*; partial ones are finished.
- **Sonar**: live progress for each day and article. **SURFACE** stops the run.
- **Logbook**: every date that has a summary file. Click one to read it, search the text or filter by ministry.

By default the server only listens on your own computer. To open it on a phone on the same Wi-Fi, start it with `PIB_WEB_HOST=0.0.0.0 python webapp/server.py` and use the phone address it prints (anyone on that Wi-Fi can then use it). Use another port with `PIB_WEB_PORT=8080`.

> Always start the server from the `pib` environment. The spider runs with the same Python as the server.

## Using the command line

Run from the project folder, the one that contains `scrapy.cfg`:

```bash
conda activate pib
source .secrets

# one date
scrapy crawl pib_daily -a rel_date=2025-06-15

# a date range
d=2025-06-10; end=2025-06-15
while [[ "$d" < "$end" || "$d" == "$end" ]]; do
  scrapy crawl pib_daily -a rel_date="$d"
  d=$(date -I --date="$d +1 day")
done
```

To fetch one ministry only, use the `pib` spider with a code from `ministries.txt`:

```bash
scrapy crawl pib -a rel_date=2025-06-15 -a rel_mincode=<code>
```

## Output

Everything is written to `~/pib/`:

| Folder | Contents |
|---|---|
| `~/pib/summaries/` | `15_Jun_2025.txt`: numbered summaries of all releases of that date |
| `~/pib/json_dir/` | `PIB_JSON_15_Jun_2025.json`: id, date, title, ministry, link and full text of each release |
| `~/pib/article_links/` | `PIB_LINKS_15_Jun_2025.txt`: links to all releases of that date |
| `~/pib/articles/` | `2025/Jun/15/<Ministry>/<PRID>.pdf`: PDFs, only when PDF download is on |

The website's logbook is simply the list of files in `~/pib/summaries/`. Stopping the server loses nothing.

## Settings

Edit `pibindia/spiders/config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `ENABLE_DAILY_SUMMARY` | `True` | Write the per-date Gemini summary file |
| `GEMINI_MODELS` | 6 free-tier models | Models tried in order; the next one is used when one reaches its limit |
| `ENABLE_PDF_DOWNLOAD` | `False` | Save each release as a PDF (needs `wkhtmltopdf`) |
| `ENABLE_TELEGRAM` | `False` | Post each summary to Telegram (needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`) |
| `PIB_LISTING_URL` | English listing | `lang=1` selects English; the site defaults to Hindi without it |

## Gemini limits

Each Gemini model has its own free-tier limits, for example 20 requests per day and 5 per minute for the Flash models and 500 per day for `gemini-3.5-flash-lite`. One request is made per article, and a busy day has 50 to 70 releases. To get through more articles the summarizer rotates through `GEMINI_MODELS`:

- **Per-minute limit** on a model: the next model is used straight away. If every model is at its per-minute limit, it waits the few seconds Google asks for.
- **Daily limit** on a model: that model is skipped until Google's daily reset. This is remembered in `~/pib/gemini_quota.json`, so later dates don't waste requests on it.
- **Every model used up**: the run stops. The summary file keeps what was done and the website marks the date as partial (◐); remaining dates in the range are not started (⧗). Run the same dates again after the reset: summaries already written are reused and only the missing articles are sent to Gemini.

With the default list that is roughly 600 articles a day on the free tier. Turn on billing for your Google project for higher limits.

## Project layout

```
pibindia/
  spiders/
    pib_daily.py      one date, all ministries
    pib.py            one date, one ministry code
    pib_archives.py   old archive site (not maintained right now)
    config.py         folders and settings
  modules/
    get_article.py    fetches an article's text
    tg_summary.py     Gemini summaries and Telegram posting
    daily_summary.py  writes the per-date summary file
webapp/
  server.py           local web server (Python standard library only)
  index.html          the PIB Depths interface
.env                  shell helpers used by the GitHub Actions workflows
.github/workflows/    scheduled workflows (Actions is disabled on this repo)
```

## Credits

Based on [nit-in/pib](https://github.com/nit-in/pib), which provides the original scraper, the PDF archive and the GitHub Actions workflows. This version adds the English listing fix, Gemini summaries and the web interface.

Data © Press Information Bureau, Government of India.
