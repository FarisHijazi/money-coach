"""Save PDF attachments of a Gmail message into ./pdfs/. Usage: gmail_pdfs.py <profile> <id>..."""
import base64, json, os, subprocess, sys
prof = sys.argv[1]; os.makedirs("pdfs", exist_ok=True)
env = dict(os.environ, GOOGLE_WORKSPACE_CLI_CONFIG_DIR=os.path.expanduser(f"~/.config/gws/profiles/{prof}"))
def g(params, *rest):
    o = subprocess.run(["gws", "gmail", "users", "messages", *rest, "--params", json.dumps(params)], capture_output=True, text=True, env=env).stdout
    return json.loads(o[o.index("{"):])
for mid in sys.argv[2:]:
    def walk(p):
        for q in p.get("parts", []): walk(q)
        if p.get("filename", "").lower().endswith(".pdf") and p["body"].get("attachmentId"):
            a = g({"userId": "me", "messageId": mid, "id": p["body"]["attachmentId"]}, "attachments", "get")
            path = f"pdfs/{mid}_{p['filename']}"; open(path, "wb").write(base64.urlsafe_b64decode(a["data"])); print(path)
    walk(g({"userId": "me", "id": mid, "format": "full"}, "get")["payload"])
