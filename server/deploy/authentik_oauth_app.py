"""Create or update the Authentik OAuth2 provider + application 'money-mcp' that claude.ai connectors use
to sign in to /mcp. Idempotent; prints only non-secret ids (the client is public: PKCE, no secret).

Run: AUTHENTIK_URL=https://auth.example.com AUTHENTIK_TOKEN=<API token> MONEY_URL=https://money.example.com \
     python3 authentik_oauth_app.py
Then set on the server: MONEY_OIDC_ISSUER=$AUTHENTIK_URL/application/o/money-mcp/ and
MONEY_OIDC_CLIENT_ID=<printed client_id>, and paste the client id into the connector's OAuth settings.
"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.environ["AUTHENTIK_URL"].rstrip("/") + "/api/v3"
H = {"Authorization": f"Bearer {os.environ['AUTHENTIK_TOKEN']}", "Content-Type": "application/json",
     "User-Agent": "money-coach-setup/1"}  # Cloudflare 1010s Python's default UA


def api(method, path, body=None, **q):
    url = BASE + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, method=method, headers=H, data=json.dumps(body).encode() if body else None)
    with urllib.request.urlopen(req) as r:
        return json.load(r) if r.status != 204 else None

def one(path, **q):
    res = api("GET", path, **q)["results"]
    assert len(res) == 1, (path, q, [x.get("slug") or x.get("name") for x in res])
    return res[0]

authz = one("/flows/instances/", slug="default-provider-authorization-explicit-consent")["pk"]
inval = one("/flows/instances/", slug="default-provider-invalidation-flow")["pk"]
certs = api("GET", "/crypto/certificatekeypairs/", has_key="true")["results"]
key = next(c["pk"] for c in certs if c["name"] == "authentik Self-signed Certificate")
scopes = [m["pk"] for m in api("GET", "/propertymappings/provider/scope/", page_size=100)["results"]
          if m.get("managed") in ("goauthentik.io/providers/oauth2/scope-openid", "goauthentik.io/providers/oauth2/scope-email",
                                  "goauthentik.io/providers/oauth2/scope-profile", "goauthentik.io/providers/oauth2/scope-offline_access")]
assert len(scopes) == 4, scopes
body = {
    "name": "money-mcp", "authorization_flow": authz, "invalidation_flow": inval,
    "client_type": "public", "signing_key": key, "property_mappings": scopes,
    "grant_types": ["authorization_code", "refresh_token"],  # API-created providers get [] otherwise
    "redirect_uris": [{"matching_mode": "strict", "url": u} for u in
                      ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback")],
    "access_token_validity": "hours=1", "refresh_token_validity": "days=30", "sub_mode": "hashed_user_id",
    "issuer_mode": "per_provider",
}
existing = api("GET", "/providers/oauth2/", name="money-mcp")["results"]
prov = api("PATCH", f"/providers/oauth2/{existing[0]['pk']}/", body) if existing else api("POST", "/providers/oauth2/", body)
apps = api("GET", "/core/applications/", slug="money-mcp")["results"]
app_body = {"name": "Money coach (MCP)", "slug": "money-mcp", "provider": prov["pk"], "meta_launch_url": os.environ["MONEY_URL"]}
app = api("PATCH", "/core/applications/money-mcp/", app_body) if apps else api("POST", "/core/applications/", app_body)
print(json.dumps({"provider_pk": prov["pk"], "client_id": prov["client_id"], "client_type": prov["client_type"],
                  "grant_types": prov["grant_types"], "app": app["slug"]}))
