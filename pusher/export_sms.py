"""Export SMS from macOS Messages (iCloud-synced from iPhone) to CSV. Needs Full Disk Access.

Run: python3 export_sms.py OUT.csv   (push.py imports export() instead)
"""
import csv
import io
import os
import sqlite3
import sys

DB = os.path.expanduser("~/Library/Messages/chat.db")

QUERY = """
SELECT datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') AS ts,
       h.id AS sender, m.is_from_me, m.service, m.text, m.attributedBody
FROM message m LEFT JOIN handle h ON h.ROWID = m.handle_id
WHERE m.service = 'SMS'
ORDER BY m.date
"""


def decode_attributed_body(blob):
    """Pull the plain string out of an NSAttributedString typedstream blob."""
    if not blob:
        return ""
    i = blob.find(b"NSString")
    if i < 0:
        return ""
    i = blob.find(b"+", i) + 1  # '+' marks the start of the length-prefixed string
    n = blob[i]
    i += 1
    if n == 0x81:  # 2-byte little-endian length
        n = int.from_bytes(blob[i:i + 2], "little"); i += 2
    elif n == 0x82:  # 4-byte length
        n = int.from_bytes(blob[i:i + 4], "little"); i += 4
    return blob[i:i + n].decode("utf-8", errors="replace")


def export():
    """All SMS as CSV bytes (with a BOM so Excel/Sheets read Arabic), and the message count."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(QUERY).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["datetime", "sender", "direction", "text"])
    for ts, sender, from_me, _svc, text, body in rows:
        w.writerow([ts, sender, "sent" if from_me else "received", text or decode_attributed_body(body)])
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), len(rows)


if __name__ == "__main__":
    data, n = export()
    open(sys.argv[1], "wb").write(data)
    print(f"{n} messages -> {sys.argv[1]}")
