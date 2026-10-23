# money-coach

Turn Saudi bank SMS alerts and account statements into a single spending ledger, a categorized
monthly breakdown, an HTML dashboard, a weekly budget check and an MCP server an AI assistant can
query. All amounts are SAR.

Supported SMS senders: Al Rajhi, Riyad Bank, SNB, SAB, ANB, Bank AlJazira, D360, STC Bank, Barq,
Emirates NBD, meem. Supported statements: Riyad, Rajhi, SNB, SAB, ANB.

## Components

```
 Mac (iPhone SMS via iCloud)            server (Docker)
 ┌──────────────────────┐   HTTPS    ┌───────────────────────────────────────────┐
 │ pusher/push.py       │──────────▶ │ POST /api/ingest → analyzer/pipeline.py   │
 │ reads chat.db (FDA)  │  bearer    │ GET  /        dashboard (behind your SSO) │
 └──────────────────────┘   token    │ GET  /weekly  weekly check                │
                                     │      /mcp     MCP server (bearer token)   │
                                     └───────────────────────────────────────────┘
```

| Dir | What | Runs on |
|---|---|---|
| `pusher/` | `export_sms.py` reads `~/Library/Messages/chat.db`; `push.py` gzips all SMS and POSTs them. Stdlib only. | a real Mac, or the `macos` compose profile |
| `analyzer/` | The parsers, categorizer, dashboard builder and weekly check. Stdlib only (PDF statement parsers also need `pdfplumber` / `pdftotext`). | anywhere; inside the server image |
| `server/` | `app.py`: one process serving ingest, the dashboard UI and MCP (`mcp` SDK). `smoke_test.py` checks a running server end to end. | Docker |

## Server

```bash
echo "MONEY_TOKEN=$(openssl rand -hex 32)" > .env && chmod 600 .env
mkdir -p data/statements && cp analyzer/personal.example.py data/personal.py   # then edit it
docker compose up -d --build            # http://127.0.0.1:8000
```

`data/` holds `personal.py`, optional `statements/<bank>.csv`, and everything the pipeline writes.
Each push replaces `data/sms-export.csv` and reruns the pipeline.

**Auth.** `/mcp` and `/api/ingest` require `Authorization: Bearer $MONEY_TOKEN`. The dashboard
(`/`, `/weekly`) has **no auth of its own**: put it behind a forward-auth proxy (Authentik,
OAuth2 Proxy, ...) and route `/mcp` + `/api/` around that proxy, since MCP clients and the pusher
cannot do a browser login. `compose.override.example.yml` shows this with Traefik.

**OAuth for `/mcp` (claude.ai connectors).** Connectors sign in with OAuth and cannot send a fixed
header. Set `MONEY_PUBLIC_URL`, `MONEY_OIDC_ISSUER` and `MONEY_OIDC_CLIENT_ID` in `.env`: `/mcp` then
also accepts JWT access tokens from that issuer (audience = the client id) and serves
`/.well-known/oauth-protected-resource/mcp` pointing clients at it. `server/deploy/authentik_oauth_app.py`
creates the matching Authentik public client. In claude.ai: add a custom connector with URL
`https://money.example.com/mcp` and, under advanced settings, that OAuth Client ID (no secret).
Route `/.well-known/` around the auth proxy too.

**MCP tools:** `status` (data freshness), `weekly_check`, `month_pace` (this month: spent vs budget,
projected month-end, SAR/day left), `month_summary(month)`,
`search_transactions(text, month, category, min_amount, limit)`, `unparsed_sms(limit)`.
For example, with Claude Code:

```bash
claude mcp add --transport http money https://money.example.com/mcp \
  --header "Authorization: Bearer $MONEY_TOKEN"
```

Check a deployment: `cd server && uv run python smoke_test.py https://money.example.com $MONEY_TOKEN`.

## Pusher

On a Mac with iPhone SMS syncing (Messages in iCloud, or Text Message Forwarding):

```bash
mkdir -p ~/.config/money-coach && chmod 700 ~/.config/money-coach
printf 'MONEY_URL=https://money.example.com\nMONEY_TOKEN=...\n' > ~/.config/money-coach/pusher.env
chmod 600 ~/.config/money-coach/pusher.env
pusher/install-macos.sh            # LaunchAgent: polls every minute, pushes on Refresh or every 30 min
```

Give the python it prints **Full Disk Access** (System Settings → Privacy & Security), or the
log (`~/Library/Logs/money-coach-pusher.log`) shows `unable to open database file`.

**Coach chat.** `coach/coach.py` (stdlib) runs on the host where Claude Code is signed in: each chat
message is one `claude -p --resume <session>` in this directory, so the conversation persists in Claude's
own store and nothing has to stay alive between messages (the official headless mode, on your
subscription; Managed Agents would need API billing and send the ledger through Anthropic's control
plane). Put the coaching brief in a gitignored `CLAUDE.local.md` and pre-approve tools in
`.claude/settings.local.json`: it runs in `dontAsk` mode, so anything not allowed is refused, never
prompted. Install with `coach/money-coach-chat.service`; set `MONEY_CHAT_URL` for the server.

**Refresh button.** The dashboard shows when the data was last rebuilt and has a Refresh button. The
server cannot read SMS itself, so Refresh only flags a request (`POST /refresh`); the pusher polls
`/api/refresh-wanted` every minute and pushes. Pipeline failures and errors the pusher reports
(`/api/pusher-error`) show under the button; so does a request the Mac has not picked up in 3 min.

**No Mac?** `docker compose --profile macos up -d` adds a macOS VM
([dockur/macos](https://github.com/dockur/macos), needs `/dev/kvm`) with `pusher/` shared in.
Steps are in `compose.yml`. Apple may block iCloud sign-in in a VM, so a real Mac is the reliable path.

## Pipeline (local, without the server)

```bash
python3 pusher/export_sms.py analyzer/sms-export.csv
cd analyzer && python3 pipeline.py && python3 weekly_check.py
```

| Step | Script | Reads | Writes |
|---|---|---|---|
| 1. Parse SMS | `parse.py` | newest `sms-export*.csv` | `ledger.csv` (bucket: income / expense / internal / property / debt / company), `unparsed.csv` |
| 2. Parse statements (optional, manual) | `statements/parse_<bank>.py` | `statements/<bank>*.pdf` | `statements/<bank>.csv` |
| 3. Reconcile (only with all 5 statement CSVs) | `reconcile.py` | `statements/*.csv`, `ledger.csv` | `flows.csv` + monthly totals |
| 4. Categorize | `categorize.py` | `ledger.csv` | `categorized.csv`, `summary.json` |
| 5. Dashboard | `build_dashboard.py` | `categorized.csv`, `flows.csv`, `dashboard_template.html` | `dashboard.html` |
| 6. Weekly check | `weekly_check.py` | `ledger.csv`, `categorized.csv` | prints last Sun–Sat week vs budget, "safe to spend", and `pace.py`'s month projection |

`pipeline.py` runs 1, 3, 4 and 5. Files live in `$MONEY_DATA` (default: `analyzer/`).

How it classifies:

- `parse.py` matches the first line of each bank SMS against `RULES` (salary, purchase, transfer,
  card payment, refund, ATM, bill, ...), extracts the SAR amount (converting foreign currency with a
  rough `FX` table when no SAR total is printed) and the counterparty, then buckets it. Duplicate
  SMS within 10 minutes are dropped, and self-transfers are paired across banks (same amount ±2 SAR,
  ≤4 days, `match` column).
- `categorize.py` gives card purchases a merchant category (`CATS` regexes) and keeps the ledger
  sub-bucket for non-card flows (loans, rent, spouse, people, bills, fees).
- `reconcile.py` classifies statement rows with your `STATEMENT_RULES` and fills statement gaps
  from SMS.
- `match_drahim.py` / `tools/` are optional helpers (compare with the Drahim app, rule
  counterfactuals, Gmail statement downloads via the `gws` CLI).

## Configure: `personal.py`

Everything personal — your name, family, income sources, tenant, account and card numbers, merchant
regexes, budgets, standing-order plan — lives in one flat module, `personal.py`, copied from
`analyzer/personal.example.py`. `config.py` loads `$MONEY_DATA/personal.py`, else
`analyzer/personal.py`, else the example, so a fresh clone runs on placeholders. Every regex runs on
the raw SMS / statement text, so write names the way your bank prints them, in Latin and Arabic.

## Privacy

`personal.py`, `data/`, the SMS exports, statements, PDFs and every generated file (`*.csv`,
`*.json`, `dashboard.html`, ...) are gitignored and never baked into the image. Bank SMS contain
account numbers and OTPs: the server holds them, so keep the dashboard behind real auth and the
token secret. The dashboard only loads Chart.js from a CDN.

Not financial advice.
