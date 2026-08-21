import os
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Можно указать один или несколько адресов через запятую.
# Пример:
# https://my-visitka.onrender.com,https://example.com
ALLOWED_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if item.strip()
}

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID is not set")

if not ALLOWED_ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS is not set")

CORS(
    app,
    resources={
        r"/api/contact": {
            "origins": list(ALLOWED_ORIGINS)
        }
    },
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 600
request_log = defaultdict(deque)


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_rate_limited(ip):
    now = time.time()
    queue = request_log[ip]

    while queue and now - queue[0] > RATE_WINDOW_SECONDS:
        queue.popleft()

    if len(queue) >= RATE_LIMIT:
        return True

    queue.append(now)
    return False


def clean(value, max_length):
    if value is None:
        return ""
    return str(value).strip()[:max_length]


@app.get("/")
def root():
    return jsonify({
        "service": "portfolio-requests",
        "ok": True
    }), 200


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


@app.post("/api/contact")
def contact():
    origin = request.headers.get("Origin", "").rstrip("/")

    if origin not in ALLOWED_ORIGINS:
        return jsonify({
            "ok": False,
            "error": "origin_not_allowed"
        }), 403

    ip = client_ip()

    if is_rate_limited(ip):
        return jsonify({
            "ok": False,
            "error": "rate_limited"
        }), 429

    if not request.is_json:
        return jsonify({
            "ok": False,
            "error": "json_required"
        }), 400

    data = request.get_json(silent=True) or {}

    # Honeypot. Настоящий посетитель это поле не видит.
    if clean(data.get("website"), 200):
        return jsonify({"ok": True}), 200

    form_type = clean(data.get("form_type"), 100)
    name = clean(data.get("name"), 120)
    email = clean(data.get("email"), 200)
    contact_value = clean(data.get("contact"), 200)
    link = clean(data.get("link"), 500)
    message = clean(data.get("message"), 3000)

    if not form_type or not message:
        return jsonify({
            "ok": False,
            "error": "missing_fields"
        }), 400

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

    lines.extend([
        "",
        "Сообщение:",
        message
    ])

    telegram_url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            telegram_url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "\n".join(lines),
                "disable_web_page_preview": True
            },
            timeout=10
        )
    except requests.RequestException:
        app.logger.exception("Telegram request failed")
        return jsonify({
            "ok": False,
            "error": "telegram_unreachable"
        }), 502

    if not response.ok:
        app.logger.error(
            "Telegram API error: status=%s body=%s",
            response.status_code,
            response.text[:500]
        )
        return jsonify({
            "ok": False,
            "error": "telegram_error"
        }), 502

    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
