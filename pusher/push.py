"""Push all SMS from this Mac's chat.db to the money-coach server, which rebuilds the ledger.

Run: python3 push.py   (stdlib only; needs Full Disk Access for chat.db)
Env, or a KEY=VALUE file at $MONEY_PUSHER_ENV (default ~/.config/money-coach/pusher.env):
  MONEY_URL    server base URL, e.g. https://money.example.com
  MONEY_TOKEN  the server's bearer token
"""
import gzip
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

from export_sms import export


def load_env():
    f = Path(os.environ.get("MONEY_PUSHER_ENV") or Path.home() / ".config/money-coach/pusher.env")
    if f.exists():
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def main():
    load_env()
    try:
        data, n = export()
    except sqlite3.OperationalError as e:
        sys.exit(f"cannot read chat.db ({e}): give Full Disk Access to {os.path.realpath(sys.executable)}")
    req = urllib.request.Request(
        os.environ["MONEY_URL"].rstrip("/") + "/api/ingest", data=gzip.compress(data), method="POST",
        # Cloudflare rejects Python's default User-Agent (error 1010)
        headers={"Authorization": f"Bearer {os.environ['MONEY_TOKEN']}", "Content-Type": "text/csv",
                 "User-Agent": "money-coach-pusher/1"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    print(f"pushed {n} SMS ({len(data) // 1024} KB) -> {res['transactions']} transactions, "
          f"newest {res['newest_transaction']}")


if __name__ == "__main__":
    sys.exit(main())
