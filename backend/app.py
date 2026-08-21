import os
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "").rstrip("/")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID is not set")
if not ALLOWED_ORIGIN:
    raise RuntimeError("ALLOWED_ORIGIN is not set")

CORS(
    app,
    resources={r"/api/contact": {"origins": [ALLOWED_ORIGIN]}},
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# Simple in-memory rate limit: 5 requests per 10 minutes per IP.
# Suitable for a small portfolio site. For multi-instance production,
# replace with Redis or another shared store.
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 600
request_log = defaultdict(deque)


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limited(ip: str) -> bool:
    now = time.time()
    q = request_log[ip]
    while q and now - q[0] > RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


def clean_text(value, max_len):
    if value is None:
        return ""
    value = str(value).strip()
    return value[:max_len]


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


@app.post("/api/contact")
def contact():
    # Origin check is an extra guard; CORS alone is browser-side policy.
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin != ALLOWED_ORIGIN:
        return jsonify({"ok": False, "error": "origin_not_allowed"}), 403

    ip = client_ip()
    if rate_limited(ip):
        return jsonify({"ok": False, "error": "rate_limited"}), 429

    if not request.is_json:
        return jsonify({"ok": False, "error": "json_required"}), 400

    data = request.get_json(silent=True) or {}

    # Honeypot: normal users never fill this hidden field.
    if clean_text(data.get("website"), 200):
        return jsonify({"ok": True}), 200

    form_type = clean_text(data.get("form_type"), 80)
    name = clean_text(data.get("name"), 100)
    contact_value = clean_text(data.get("contact"), 200)
    email = clean_text(data.get("email"), 200)
    link = clean_text(data.get("link"), 500)
    message = clean_text(data.get("message"), 3000)

    if not form_type or not message:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    lines = [
        "📩 Новая заявка с портфолио",
        "",
        f"Тип: {form_type}",
    ]
    if name:
        lines.append(f"Имя: {name}")
    if email:
        lines.append(f"Email: {email}")
    if contact_value:
        lines.append(f"Контакт: {contact_value}")
    if link:
        lines.append(f"Ссылка: {link}")
    lines.extend(["", "Сообщение:", message])

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            telegram_url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "\n".join(lines),
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except requests.RequestException:
        return jsonify({"ok": False, "error": "telegram_unreachable"}), 502

    if not response.ok:
        return jsonify({"ok": False, "error": "telegram_error"}), 502

    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
