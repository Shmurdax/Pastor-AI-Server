from flask import Flask, request, abort
import hmac, hashlib, subprocess, os

app = Flask(__name__)
SECRET = os.environ["WEBHOOK_SECRET"].encode()

BRANCH_TO_SCRIPT = {
    "refs/heads/development": "/opt/pastor-ai/deploy-dev.sh",
    "refs/heads/server_backup": "/opt/pastor-ai/deploy-backup.sh",
}

@app.post("/deploy")
def deploy():
    sig = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()

    expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(403)

    payload = request.json or {}
    ref = payload.get("ref", "")
    script = BRANCH_TO_SCRIPT.get(ref)

    if not script:
        return f"ignored ({ref})", 200

    subprocess.Popen([script])
    return f"deploy started for {ref}", 202

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9001)
