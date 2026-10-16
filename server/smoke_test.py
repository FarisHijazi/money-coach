"""End-to-end check of a running server: auth gates, every MCP tool, the UI.

Run: uv run python smoke_test.py BASE_URL TOKEN   (the UI check is skipped when BASE_URL is https,
since there Authentik answers first; it must redirect, never serve the dashboard)
"""
import asyncio
import sys
import urllib.request
from urllib.error import HTTPError

from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

BASE, TOKEN = sys.argv[1].rstrip("/"), sys.argv[2]
UA = {"User-Agent": "money-coach-smoke/1"}  # Cloudflare 1010s Python's default UA


def code(path, method="GET", headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None,
                                 headers={**UA, **(headers or {})})
    opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                                              {"redirect_request": lambda *a: None}))
    try:
        return opener.open(req, timeout=30).status
    except HTTPError as e:
        return e.code


async def tools():
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {TOKEN}", **UA})
    async with Client(streamable_http_client(BASE + "/mcp", http_client=http)) as c:
        names = sorted(t.name for t in (await c.list_tools()).tools)
        print("tools:", names)
        for name, args in [("status", {}), ("weekly_check", {}), ("month_summary", {}),
                           ("search_transactions", {"limit": 2}), ("unparsed_sms", {"limit": 1})]:
            r = await c.call_tool(name, args)
            text = " ".join(getattr(x, "text", "") for x in r.content)
            assert not r.is_error, (name, text)
            print(f"  {name}: {text[:160]!r}")


checks = {"mcp without token": (code("/mcp", "POST"), 401),
          "ingest without token": (code("/api/ingest", "POST"), 401),
          "ingest with bad token": (code("/api/ingest", "POST", {"Authorization": "Bearer nope"}), 401),
          "health": (code("/api/health"), 200)}
ui = code("/")
checks["UI"] = (ui, 302) if BASE.startswith("https") else (ui, 200)
for k, (got, want) in checks.items():
    print(f"{'ok ' if got == want else 'FAIL'} {k}: {got} (want {want})")
asyncio.run(tools())
sys.exit(0 if all(g == w for g, w in checks.values()) else 1)
