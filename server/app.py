"""money-coach server: SMS ingest, the dashboard web UI, and an MCP server over the analyzer's outputs.

Routes (one process, one port):
  POST /api/ingest   bearer token. Body: the pusher's SMS CSV (gzip ok). Saves it, reruns the pipeline.
  GET  /api/health   public. Only says when data last arrived.
  GET  /api/refresh-wanted   bearer. The pusher polls this; true after someone pressed Refresh.
  POST /api/pusher-error     bearer. Body: text. The pusher reports a failure it hit on the Mac.
  /mcp               bearer: MONEY_TOKEN, or an OAuth access token from MONEY_OIDC_ISSUER (claude.ai
                     connectors). MCP streamable HTTP: weekly_check, month_summary, search_transactions...
  /.well-known/oauth-protected-resource/mcp   public. Points OAuth clients at MONEY_OIDC_ISSUER.
  GET  /             the dashboard. NO auth here: put it behind an auth proxy (Authentik in our deploy).
  GET  /weekly       weekly check as plain text, same proxy.
  POST /refresh      same proxy. Asks the Mac pusher to push now (it polls every minute).
  GET  /refresh-status   same proxy. Last push/rebuild, pending request, last error.
  GET  /chat/history, POST /chat/send, POST /chat/new   same proxy. Forwarded to coach/coach.py on the host.

Env: MONEY_TOKEN (required), MONEY_DATA (data dir, default ../analyzer), PORT (default 8000),
     MONEY_PUBLIC_URL (e.g. https://money.example.com), MONEY_OIDC_ISSUER + MONEY_OIDC_CLIENT_ID
     (optional OAuth: tokens must be JWTs from that issuer with aud = that client id),
     MONEY_CHAT_URL (coach/coach.py, e.g. http://172.17.0.1:8390; the chat panel hides when unset).
"""
import asyncio
import csv
import gzip
import hmac
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx
import jwt
import uvicorn
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response

ANALYZER = Path(__file__).resolve().parent.parent / "analyzer"
sys.path.insert(0, str(ANALYZER))
from categorize import GROUP, label  # noqa: E402
import pace  # noqa: E402
from config import DATA  # noqa: E402
import pipeline  # noqa: E402

TOKEN = os.environ["MONEY_TOKEN"]
PUBLIC_URL = (os.environ.get("MONEY_PUBLIC_URL") or "http://localhost:8000").rstrip("/")
ISSUER, CLIENT_ID = os.environ.get("MONEY_OIDC_ISSUER"), os.environ.get("MONEY_OIDC_CLIENT_ID")
CHAT = (os.environ.get("MONEY_CHAT_URL") or "").rstrip("/")
LOCK = asyncio.Lock()
REQUESTED = DATA / "refresh-requested"  # exists while a Refresh press waits for the pusher; mtime = when
ERROR = DATA / "last-error.json"        # the newest ingest/pusher failure; cleared by the next good ingest


class Verifier:
    """/mcp accepts the static MONEY_TOKEN (pusher, Claude Code) or a JWT access token from the OIDC issuer."""
    # Cloudflare 1010s Python's default User-Agent, and the issuer may sit behind it
    jwks = jwt.PyJWKClient(f"{ISSUER}jwks/", headers={"User-Agent": "money-coach/1"}) if ISSUER else None

    async def verify_token(self, token: str) -> AccessToken | None:
        resource = f"{PUBLIC_URL}/mcp"
        if hmac.compare_digest(token.encode(), TOKEN.encode()):
            return AccessToken(token=token, client_id="static-token", scopes=[], resource=resource)
        if not self.jwks:
            return None
        try:
            key = await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)
            c = jwt.decode(token, key.key, algorithms=["RS256", "ES256"], audience=CLIENT_ID, issuer=ISSUER)
        except jwt.PyJWTError:
            return None
        return AccessToken(token=token, client_id=CLIENT_ID, scopes=c.get("scope", "").split(),
                           expires_at=c.get("exp"), resource=resource, subject=c.get("sub"))


mcp = MCPServer(
    "money-coach",
    token_verifier=Verifier(),
    # validate_token_resource=False: Authentik puts the client id in aud, which Verifier checks itself
    auth=AuthSettings(issuer_url=ISSUER or PUBLIC_URL, resource_server_url=f"{PUBLIC_URL}/mcp",
                      validate_token_resource=False),
    instructions="Personal spending ledger built from bank SMS. Amounts are SAR. Call status first to see "
    "how fresh the data is. Never suggest executing transfers; for investment talk add 'not a licensed advisor'.",
)


def rows(name):
    f = DATA / name
    return list(csv.DictReader(open(f, encoding="utf-8-sig"))) if f.exists() else []


def weekly_text():
    r = subprocess.run([sys.executable, str(ANALYZER / "weekly_check.py")], cwd=ANALYZER,
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else f"weekly_check failed: {r.stderr.strip()[-500:]}"


def mtime(name):
    f = DATA / name
    return datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds") if f.exists() else None


def set_error(source, message):
    ERROR.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "source": source,
                                 "message": message[-2000:]}))


def refresh_state():
    return {"last_push": mtime("sms-export.csv"), "last_rebuild": mtime("dashboard.html"),
            "requested": mtime(REQUESTED.name), "error": json.loads(ERROR.read_text()) if ERROR.exists() else None}


# ---------- MCP tools ----------

@mcp.tool()
def status() -> dict:
    """How fresh the data is: when SMS were last pushed, and the newest transaction in the ledger."""
    ledger = rows("ledger.csv")
    return {"last_push": mtime("sms-export.csv"), "last_rebuild": mtime("dashboard.html"),
            "transactions": len(ledger), "newest_transaction": max((x["datetime"] for x in ledger), default=None),
            "unparsed_sms": len(rows("unparsed.csv"))}


@mcp.tool()
def weekly_check() -> str:
    """Grade last Sun–Sat week vs the weekly budget, plus SAFE TO SPEND for this month."""
    return weekly_text()


@mcp.tool()
def month_pace() -> dict:
    """This month so far: per budget group, spent vs budget and the projected month-end total (fixed costs at
    budget, the rest at the current daily rate), plus how much variable spending is left per day."""
    return pace.compute()


@mcp.tool()
def month_summary(month: str = "") -> dict:
    """Spending per category and per group for one month ("YYYY-MM", default this month)."""
    month = month or date.today().strftime("%Y-%m")
    cats, groups, n = defaultdict(float), defaultdict(float), 0
    for r in rows("categorized.csv"):
        if r["datetime"].startswith(month):
            a = float(r["amount"])
            cats[r["category"]] += a
            groups[GROUP.get(r["category"], "Unknown")] += a
            n += 1
    by = lambda d: {label(k): round(v, 2) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}  # noqa: E731
    return {"month": month, "transactions": n, "total": round(sum(cats.values()), 2),
            "by_group": by(groups), "by_category": by(cats)}


@mcp.tool()
def search_transactions(text: str = "", month: str = "", category: str = "", min_amount: float = 0,
                        limit: int = 50) -> list[dict]:
    """Categorized spending, newest first. Filters: text (in merchant/SMS, case-insensitive), month
    ("YYYY-MM" or "YYYY"), category (exact name from month_summary), min_amount (SAR)."""
    t = text.lower()
    out = [r for r in rows("categorized.csv")
           if (not t or t in (r["merchant"] + r["counterparty"] + r["text"]).lower())
           and r["datetime"].startswith(month) and (not category or category in (r["category"], label(r["category"])))
           and float(r["amount"]) >= min_amount]
    out = sorted(out, key=lambda r: r["datetime"], reverse=True)[:limit]
    return [{**r, "category": label(r["category"])} for r in out]


@mcp.tool()
def unparsed_sms(limit: int = 20) -> list[dict]:
    """Newest bank SMS that looked like transactions but no parser rule matched (gaps in the ledger)."""
    return sorted(rows("unparsed.csv"), key=lambda r: r["datetime"], reverse=True)[:limit]


# ---------- HTTP routes ----------

@mcp.custom_route("/api/ingest", methods=["POST"])
async def ingest(request: Request) -> Response:
    body = await request.body()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    if not body.lstrip(b"\xef\xbb\xbf").startswith(b"datetime,sender,direction,text"):
        return JSONResponse({"error": "expected the pusher's SMS CSV"}, status_code=400)
    async with LOCK:
        tmp = DATA / "sms-export.csv.tmp"
        tmp.write_bytes(body)
        tmp.replace(DATA / "sms-export.csv")
        try:
            steps = await asyncio.to_thread(pipeline.run)
        except subprocess.CalledProcessError as e:
            set_error("server pipeline", f"{Path(e.cmd[1]).name} failed: {(e.stderr or '').strip()}")
            return JSONResponse({"error": json.loads(ERROR.read_text())}, status_code=500)
        ERROR.unlink(missing_ok=True)
        REQUESTED.unlink(missing_ok=True)
    return JSONResponse({"bytes": len(body), "steps": steps, **status()})


@mcp.custom_route("/api/refresh-wanted", methods=["GET"])
async def refresh_wanted(_: Request) -> Response:
    return JSONResponse({"wanted": REQUESTED.exists()})


@mcp.custom_route("/api/pusher-error", methods=["POST"])
async def pusher_error(request: Request) -> Response:
    set_error("Mac pusher", (await request.body()).decode(errors="replace"))
    return JSONResponse({"ok": True})


@mcp.custom_route("/refresh", methods=["POST"])
async def refresh(_: Request) -> Response:
    ERROR.unlink(missing_ok=True)  # a fresh attempt; it records its own error if it fails again
    REQUESTED.touch()
    return JSONResponse(refresh_state())


@mcp.custom_route("/chat/{op}", methods=["GET", "POST"])
async def chat(request: Request) -> Response:
    if not CHAT:
        return JSONResponse({"error": "chat is not configured (MONEY_CHAT_URL)"}, status_code=404)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(request.method, f"{CHAT}/{request.path_params['op']}", content=await request.body(),
                                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        return JSONResponse({"error": f"coach service unreachable: {e!r}"}, status_code=502)
    return Response(r.content, status_code=r.status_code, media_type="application/json")


@mcp.custom_route("/refresh-status", methods=["GET"])
async def refresh_status(_: Request) -> Response:
    return JSONResponse(refresh_state())


@mcp.custom_route("/api/health", methods=["GET"])
async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "last_push": mtime("sms-export.csv")})


@mcp.custom_route("/", methods=["GET"])
async def dashboard(_: Request) -> Response:
    f = DATA / "dashboard.html"
    if not f.exists():
        return PlainTextResponse("No data yet: run the pusher (see README).", status_code=503)
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@mcp.custom_route("/weekly", methods=["GET"])
async def weekly(_: Request) -> Response:
    return PlainTextResponse(weekly_text())


def require_token(app):
    """ASGI wrapper: /api/* except /api/health needs `Authorization: Bearer $MONEY_TOKEN` (/mcp: Verifier)."""
    want = f"Bearer {TOKEN}".encode()

    async def wrapped(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/") and scope["path"] != "/api/health":
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, want):
                return await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
        await app(scope, receive, send)
    return wrapped


# host 0.0.0.0: DNS-rebinding protection is for localhost-only servers; this one sits behind a proxy
app = require_token(mcp.streamable_http_app(stateless_http=True, host="0.0.0.0"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), proxy_headers=True)
