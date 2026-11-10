from pathlib import Path

from pibindia.modules.tg_summary import summarize_text


def write_daily_summary(articles, summary_dir, file_date):
    """Summarize every article of one date into a single file.

    articles   : list of dicts built by article_jdata (id, date, title, ministry, url, article)
    summary_dir: folder for the summary files, e.g. "~/pib/summaries"
    file_date  : date part of the file name, e.g. "15_Jun_2025"
    """
    if not articles:
        print(f"No articles for {file_date}, no summary file written.")
        return None

    out_dir = Path(summary_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_date}.txt"

    total = len(articles)
    print(f"Writing summaries of {total} articles to {out_path}")

    # Written article by article, so progress is kept if the run stops midway
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"PIB summaries for {file_date.replace('_', ' ')} ({total} articles)\n\n")
        for sr, art in enumerate(articles, 1):
            print(f"Summarizing article {sr}/{total}: {art['id']}")
            text = art.get("article")
            summary = summarize_text(text) if text else "(article text could not be fetched)"

            f.write(f"{sr}. {art['title'].strip()}\n")
            f.write(f"Ministry: {art['ministry'].strip()}\n")
            f.write(f"Link: {art['url']}\n\n")
            f.write(f"{summary.strip()}\n")
            f.write("\n" + "-" * 80 + "\n\n")
            f.flush()

    print(f"Summary file done: {out_path}")
    return str(out_path)
