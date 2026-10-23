"""Coach chat: one ongoing Claude Code conversation in the money-coach directory, for the dashboard's chat.

Runs on the host where Claude Code is signed in (not in the server container; see README). Each message
is one `claude -p --resume <session>` run in WORKDIR, so nothing stays alive between messages: the
conversation lives in Claude's own session store, the chat log below is only what the UI shows.
The money server proxies its /chat/* routes here. Stdlib only.

Routes (all need `Authorization: Bearer $MONEY_TOKEN`):
  GET  /history  -> {"busy": bool, "messages": [{"role": "user|assistant|tool|error", "text", "at"}]}
  POST /send     body {"text": "..."} -> 202; 409 while the previous reply is still running
  POST /new      next message starts a fresh conversation (the log keeps a divider)

Env: MONEY_TOKEN, COACH_WORKDIR (default: this repo), COACH_BIND (default 127.0.0.1), COACH_PORT (8390),
     COACH_STATE (default ~/.local/state/money-coach-chat), CLAUDE_BIN (default: claude on PATH)
"""
import hmac
import json
import os
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ["MONEY_TOKEN"]
WORKDIR = Path(os.environ.get("COACH_WORKDIR") or Path(__file__).resolve().parent.parent)
STATE = Path(os.environ.get("COACH_STATE") or Path.home() / ".local/state/money-coach-chat")
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
LOG, SESSION = STATE / "chat.jsonl", STATE / "session-id"
TIMEOUT = 900  # seconds per reply
BUSY = threading.Lock()


def log(role, text):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"role": role, "text": text, "at": datetime.now().isoformat(timespec="seconds")}) + "\n")


def history():
    lines = LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []
    return {"busy": BUSY.locked(), "messages": [json.loads(x) for x in lines[-300:]]}


def tool_line(block):
    """One short line per tool call, e.g. `Bash: python3 analyzer/pace.py`."""
    i = block.get("input") or {}
    detail = i.get("command") or i.get("file_path") or i.get("pattern") or i.get("query") or i.get("url") or ""
    return f"{block.get('name')}: {detail}"[:200]


def reply(text):
    """Run one turn of the conversation and log what Claude says and does as it streams. Holds BUSY."""
    try:
        cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk"]
        if SESSION.exists():
            cmd += ["--resume", SESSION.read_text().strip()]
        p = subprocess.Popen(cmd + [text], cwd=WORKDIR, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        timer = threading.Timer(TIMEOUT, p.kill)
        timer.start()
        result = None
        for line in p.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "assistant":
                for b in e["message"].get("content", []):
                    if b.get("type") == "text" and b["text"].strip():
                        log("assistant", b["text"])
                    elif b.get("type") == "tool_use":
                        log("tool", tool_line(b))
            elif e.get("type") == "result":
                result = e
                if e.get("session_id"):
                    SESSION.write_text(e["session_id"])
        p.wait()
        timer.cancel()
        if result is None or result.get("is_error"):
            why = (result or {}).get("result") or p.stderr.read().strip()[-1000:] or f"exit code {p.returncode}"
            log("error", f"Claude failed: {why}" + (" (timed out)" if p.returncode == -9 else ""))
    except OSError as e:
        log("error", f"could not start Claude ({CLAUDE}): {e}")
    finally:
        BUSY.release()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), f"Bearer {TOKEN}".encode()):
            return True
        self.send(401, {"error": "unauthorized"})
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/history":
            return self.send(200, history())
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path == "/new":
            if BUSY.locked():
                return self.send(409, {"error": "wait for the current reply"})
            SESSION.unlink(missing_ok=True)
            log("divider", "New conversation")
            return self.send(200, history())
        if self.path != "/send":
            return self.send(404, {"error": "not found"})
        try:
            text = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))["text"].strip()
        except (ValueError, KeyError, AttributeError):
            return self.send(400, {"error": 'expected {"text": "..."}'})
        if not text:
            return self.send(400, {"error": "empty message"})
        if not BUSY.acquire(blocking=False):
            return self.send(409, {"error": "still answering the previous message"})
        log("user", text)
        threading.Thread(target=reply, args=(text,), daemon=True).start()
        self.send(202, history())

    def log_message(self, *_):
        pass  # the chat log is the record; per-request access logs are noise


if __name__ == "__main__":
    STATE.mkdir(parents=True, exist_ok=True)
    bind, port = os.environ.get("COACH_BIND", "127.0.0.1"), int(os.environ.get("COACH_PORT", 8390))
    print(f"coach chat on http://{bind}:{port}, workdir {WORKDIR}", flush=True)
    ThreadingHTTPServer((bind, port), Handler).serve_forever()
