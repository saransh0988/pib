"""PIB Depths - local web interface for the pib_daily spider.

Run from anywhere:
    python /home/saranshgoel/Downloads/pib/webapp/server.py
then open http://127.0.0.1:8000
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent  # folder with scrapy.cfg
WEB_DIR = Path(__file__).resolve().parent
SUMMARY_DIR = Path("~/pib/summaries").expanduser()
SECRETS = ROOT / ".secrets"

# 127.0.0.1 = this computer only; PIB_WEB_HOST=0.0.0.0 also allows phones on the same Wi-Fi
HOST = os.getenv("PIB_WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("PIB_WEB_PORT", "8000"))


def lan_ip():
    """This computer's address on the local network (best guess)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
FIRST_DATE = date(2017, 1, 1)  # main PIB site's year dropdown starts at 2017
MAX_DAYS = 31
SEPARATOR = "-" * 80


def load_secrets():
    """Read `export KEY="value"` lines from .secrets into a dict (never logged)."""
    env = {}
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            m = re.match(r'\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*"?([^"]*)"?\s*$', line)
            if m:
                env[m.group(1)] = m.group(2)
    return env


def file_date(d):
    return d.strftime("%d_%b_%Y")  # same naming the spider uses: 15_Jun_2025


def summary_path(d):
    return SUMMARY_DIR / f"{file_date(d)}.txt"


def summary_progress(text):
    """(articles in header, articles written) for a summary file's text."""
    m = re.search(r"\((\d+) articles\)", text.split("\n", 1)[0])
    total = int(m.group(1)) if m else None
    return total, text.count(SEPARATOR)  # one separator per finished article


def summary_complete(d):
    p = summary_path(d)
    if not p.exists():
        return False
    total, written = summary_progress(p.read_text(encoding="utf-8"))
    return total is not None and written >= total


# ---------------------------------------------------------------- summaries


def parse_summary_file(path):
    text = path.read_text(encoding="utf-8")
    blocks = text.split(SEPARATOR)
    header = ""
    entries = []
    for i, block in enumerate(blocks):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        if i == 0 and lines and lines[0].startswith("PIB summaries for"):
            header = lines[0]
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
        if not lines:
            continue
        m = re.match(r"(\d+)\.\s+(.*)", lines[0])
        if not m:
            continue
        entry = {"sr": int(m.group(1)), "title": m.group(2), "ministry": "", "link": "", "summary": ""}
        rest = lines[1:]
        while rest and (rest[0].startswith("Ministry:") or rest[0].startswith("Link:")):
            key, _, val = rest[0].partition(":")
            entry[key.lower()] = val.strip()
            rest = rest[1:]
        entry["summary"] = "\n".join(rest).strip()
        entries.append(entry)
    return {"header": header, "entries": entries}


def list_summaries():
    out = []
    if SUMMARY_DIR.exists():
        for p in SUMMARY_DIR.glob("*.txt"):
            try:
                d = datetime.strptime(p.stem, "%d_%b_%Y").date()
            except ValueError:
                continue
            total, written = summary_progress(p.read_text(encoding="utf-8"))
            out.append({
                "date": d.isoformat(),
                "label": d.strftime("%d %b %Y"),
                "weekday": d.strftime("%a"),
                "articles": total,
                "written": written,
                "complete": total is not None and written >= total,
            })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# ---------------------------------------------------------------- run job


class Job:
    """One background run over a date range (only one at a time)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.running = False
        self.cancel_requested = False
        self.proc = None
        self.dates = []
        self.day_index = 0
        self.current = None
        self.article = 0
        self.articles_total = 0
        self.fetched = 0
        self.results = []  # {date, status, articles}
        self.log = []
        self.started = None
        self.finished = None
        self.error = None
        self.quota_out = False  # Gemini daily limit used up on every model

    def add_log(self, line):
        self.log.append(line)
        del self.log[:-150]

    def status(self):
        with self.lock:
            return {
                "running": self.running,
                "dates": [d.isoformat() for d in self.dates],
                "day_index": self.day_index,
                "current": self.current.isoformat() if self.current else None,
                "article": self.article,
                "articles_total": self.articles_total,
                "fetched": self.fetched,
                "results": self.results,
                "log": self.log[-60:],
                "started": self.started,
                "finished": self.finished,
                "error": self.error,
                "cancelled": self.cancel_requested,
            }

    def start(self, start, end, force):
        with self.lock:
            if self.running:
                return False, "A dive is already in progress."
            self.reset()
            self.running = True
            self.dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            self.started = datetime.now().isoformat(timespec="seconds")
        threading.Thread(target=self._run, args=(force,), daemon=True).start()
        return True, "started"

    def cancel(self):
        with self.lock:
            if not self.running:
                return False
            self.cancel_requested = True
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        return True

    def _run(self, force):
        env = os.environ.copy()
        env.update(load_secrets())
        env["PYTHONUNBUFFERED"] = "1"
        if not env.get("GEMINI_API_KEY"):
            with self.lock:
                self.error = "GEMINI_API_KEY not found in .secrets - summaries will fail."
        try:
            for i, d in enumerate(self.dates):
                with self.lock:
                    if self.cancel_requested:
                        break
                    if self.quota_out:
                        self.results.append({"date": d.isoformat(), "status": "quota", "articles": None})
                        self.add_log(f"{d}: not started, Gemini free quota used up for today")
                        continue
                    self.day_index, self.current = i, d
                    self.article, self.articles_total, self.fetched = 0, 0, 0
                if not force and summary_complete(d):
                    with self.lock:
                        self.results.append({"date": d.isoformat(), "status": "skipped", "articles": None})
                        self.add_log(f"{d}: summary already exists, skipped")
                    continue
                self._run_day(d, env)
        except Exception as e:  # keep the server alive whatever happens
            with self.lock:
                self.error = f"{type(e).__name__}: {e}"
        finally:
            with self.lock:
                self.running = False
                self.current = None
                self.proc = None
                self.finished = datetime.now().isoformat(timespec="seconds")

    def _run_day(self, d, env):
        cmd = [sys.executable, "-m", "scrapy", "crawl", "pib_daily",
               "-a", f"rel_date={d.isoformat()}",
               "-s", "LOG_LEVEL=WARNING", "-s", "COOKIES_DEBUG=False"]
        with self.lock:
            self.add_log(f"{d}: diving...")
            self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1)
            proc = self.proc
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line or "Deprecat" in line or "yield FormRequest" in line:
                continue
            with self.lock:
                if line.startswith("Fetching URL"):
                    self.fetched += 1
                elif m := re.match(r"Summarizing article (\d+)/(\d+)", line):
                    self.article, self.articles_total = int(m.group(1)), int(m.group(2))
                    self.add_log(f"{d}: summarizing {m.group(1)}/{m.group(2)}")
                elif line.startswith("Gemini") and line.endswith(": ok"):
                    pass  # one per article, too chatty for the console
                elif line.startswith(("Gemini", "Summary file done", "No articles", "Traceback")) \
                        or "Error" in line:
                    if line.startswith("Gemini quota exhausted"):
                        self.quota_out = True
                    self.add_log(f"{d}: {line}")
        code = proc.wait()
        with self.lock:
            if self.cancel_requested:
                status = "cancelled"
            elif code != 0:
                status = "failed"
            elif summary_complete(d):
                status = "done"
            elif summary_path(d).exists():
                status = "partial"  # stopped by Gemini quota; run again later to finish
            else:
                status = "empty"  # no releases that day
            self.results.append({"date": d.isoformat(), "status": status,
                                 "articles": self.articles_total or None})
            self.add_log(f"{d}: {status}")


JOB = Job()


# ---------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = (WEB_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/status":
            self.send_json(JOB.status())
        elif url.path == "/api/summaries":
            self.send_json({"summaries": list_summaries(), "today": date.today().isoformat()})
        elif url.path == "/api/summary":
            q = parse_qs(url.query)
            try:
                d = date.fromisoformat(q.get("date", [""])[0])
            except ValueError:
                return self.send_json({"error": "bad date"}, 400)
            p = summary_path(d)
            if not p.exists():
                return self.send_json({"error": "No summary for this date yet."}, 404)
            data = parse_summary_file(p)
            data.update(date=d.isoformat(), label=d.strftime("%d %B %Y"), weekday=d.strftime("%A"))
            self.send_json(data)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "bad json"}, 400)

        if url.path == "/api/run":
            try:
                start = date.fromisoformat(payload.get("start", ""))
                end = date.fromisoformat(payload.get("end", "") or payload.get("start", ""))
            except ValueError:
                return self.send_json({"error": "Pick valid dates."}, 400)
            today = date.today()
            if start > end:
                return self.send_json({"error": "Start date is after end date."}, 400)
            if start < FIRST_DATE:
                return self.send_json({"error": "The PIB site only goes back to 1 Jan 2017."}, 400)
            if end > today:
                return self.send_json({"error": "End date is in the future."}, 400)
            if (end - start).days + 1 > MAX_DAYS:
                return self.send_json({"error": f"Pick at most {MAX_DAYS} days at a time."}, 400)
            ok, msg = JOB.start(start, end, bool(payload.get("force")))
            return self.send_json({"ok": ok, "message": msg}, 200 if ok else 409)

        if url.path == "/api/cancel":
            return self.send_json({"ok": JOB.cancel()})

        self.send_json({"error": "not found"}, 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if HOST == "0.0.0.0":
        print(f"PIB Depths running at http://127.0.0.1:{PORT} on this computer")
        ip = lan_ip()
        if ip:
            print(f"On your phone (same Wi-Fi):  http://{ip}:{PORT}")
        print("(Ctrl+C to stop)")
    else:
        print(f"PIB Depths running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        JOB.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
