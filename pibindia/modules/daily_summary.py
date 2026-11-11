import re
from pathlib import Path

from pibindia.modules.tg_summary import GeminiQuotaExhausted, summarize_text

SEPARATOR = "-" * 80


def _existing_summaries(path):
    """Link -> summary for articles already summarized in an earlier (stopped) run."""
    done = {}
    if not path.exists():
        return done
    for block in path.read_text(encoding="utf-8").split(SEPARATOR):
        m = re.search(r"^Link: (\S+)\n\n(.*)", block, flags=re.M | re.S)
        if m and m.group(2).strip():
            done[m.group(1)] = m.group(2).strip()
    return done


def write_daily_summary(articles, summary_dir, file_date):
    """Summarize every article of one date into a single file.

    articles   : list of dicts built by article_jdata (id, date, title, ministry, url, article)
    summary_dir: folder for the summary files, e.g. "~/pib/summaries"
    file_date  : date part of the file name, e.g. "15_Jun_2025"

    If Gemini runs out of free quota the file is left incomplete; running the same date
    again keeps the summaries already written and only asks Gemini for the missing ones.
    """
    if not articles:
        print(f"No articles for {file_date}, no summary file written.")
        return None

    out_dir = Path(summary_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_date}.txt"

    total = len(articles)
    previous = _existing_summaries(out_path)
    print(f"Writing summaries of {total} articles to {out_path}"
          + (f" ({len(previous)} reused from earlier run)" if previous else ""))

    missing = 0
    # Written article by article, so progress is kept if the run stops midway
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"PIB summaries for {file_date.replace('_', ' ')} ({total} articles)\n\n")
        for sr, art in enumerate(articles, 1):
            print(f"Summarizing article {sr}/{total}: {art['id']}")
            text = art.get("article")
            if art["url"] in previous:
                summary = previous[art["url"]]
            elif missing:  # quota already gone: only keep what earlier runs wrote
                missing += 1
                continue
            elif not text:
                summary = "(article text could not be fetched)"
            else:
                try:
                    summary = summarize_text(text)
                except GeminiQuotaExhausted as e:
                    print(f"{e}.")
                    missing += 1
                    continue

            f.write(f"{sr}. {art['title'].strip()}\n")
            f.write(f"Ministry: {art['ministry'].strip()}\n")
            f.write(f"Link: {art['url']}\n\n")
            f.write(f"{summary.strip()}\n")
            f.write("\n" + SEPARATOR + "\n\n")
            f.flush()

    if missing:
        print(f"Gemini quota exhausted: {total - missing}/{total} articles summarized; "
              "run this date again after the daily reset to finish it.")
    else:
        print(f"Summary file done: {out_path}")
    return str(out_path)
