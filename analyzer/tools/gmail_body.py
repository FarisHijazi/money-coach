"""Print the text body of a Gmail message. Usage: gmail_body.py <gws-profile> <message-id>"""
import base64, html, json, os, re, subprocess, sys

prof, mid = sys.argv[1], sys.argv[2]
env = dict(os.environ, GOOGLE_WORKSPACE_CLI_CONFIG_DIR=os.path.expanduser(f"~/.config/gws/profiles/{prof}"))
o = subprocess.run(["gws", "gmail", "users", "messages", "get", "--params",
                    json.dumps({"userId": "me", "id": mid, "format": "full"})], capture_output=True, text=True, env=env).stdout
d = json.loads(o[o.index("{"):])
texts = []


def walk(p):
    for q in p.get("parts", []):
        walk(q)
    if p.get("body", {}).get("data") and p.get("mimeType", "").startswith("text/"):
        t = base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "ignore")
        t = re.sub(r"<style.*?</style>|<script.*?</script>", "", t, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        texts.append(re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t‌\xa0]+", " ", t)))


walk(d["payload"])
print(max(texts, key=len) if texts else "")
