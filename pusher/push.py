"""Push all SMS from this Mac's chat.db to the money-coach server, which rebuilds the ledger.

Run every minute (install-macos.sh): it pushes when the dashboard's Refresh button asked for it, or when
the last push is EVERY seconds old; otherwise it only asks the server and exits. --force always pushes.
Failures on this Mac are reported to the server so the dashboard can show them.
Run: python3 push.py [--force]   (stdlib only; needs Full Disk Access for chat.db)
Env, or a KEY=VALUE file at $MONEY_PUSHER_ENV (default ~/.config/money-coach/pusher.env):
  MONEY_URL    server base URL, e.g. https://money.example.com
  MONEY_TOKEN  the server's bearer token
"""
import gzip
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

from export_sms import export

EVERY = 1800  # seconds between unrequested pushes
STAMP = Path.home() / ".cache/money-coach/last-push"


def load_env():
    f = Path(os.environ.get("MONEY_PUSHER_ENV") or Path.home() / ".config/money-coach/pusher.env")
    if f.exists():
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def api(path, data=None, timeout=30):
    req = urllib.request.Request(
        os.environ["MONEY_URL"].rstrip("/") + path, data=data, method="POST" if data is not None else "GET",
        # Cloudflare rejects Python's default User-Agent (error 1010)
        headers={"Authorization": f"Bearer {os.environ['MONEY_TOKEN']}", "Content-Type": "text/csv",
                 "User-Agent": "money-coach-pusher/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def wanted():
    try:
        return api("/api/refresh-wanted")["wanted"]
    except OSError:
        return False  # offline: the scheduled push below logs the real error


def main():
    load_env()
    due = not STAMP.exists() or time.time() - STAMP.stat().st_mtime >= EVERY
    if not ("--force" in sys.argv or due or wanted()):
        return
    try:
        data, n = export()
    except sqlite3.OperationalError as e:
        msg = f"cannot read chat.db ({e}): give Full Disk Access to {os.path.realpath(sys.executable)}"
        try:
            api("/api/pusher-error", msg.encode())
        finally:
            sys.exit(msg)
    res = api("/api/ingest", gzip.compress(data), timeout=300)
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.touch()
    print(f"pushed {n} SMS ({len(data) // 1024} KB) -> {res['transactions']} transactions, "
          f"newest {res['newest_transaction']}")


if __name__ == "__main__":
    sys.exit(main())
