import ipaddress
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException


def env_int(name, default, minimum, maximum):
    raw_value = os.getenv(name, str(default)).strip()

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc

    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}"
        )

    return value


def env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Можно указать один или несколько точных адресов через запятую.
# Пример: https://my-visitka.onrender.com,https://example.com
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

MAX_BODY_BYTES = env_int("MAX_BODY_BYTES", 16 * 1024, 1024, 64 * 1024)
GLOBAL_RATE_LIMIT = env_int("GLOBAL_RATE_LIMIT", 120, 10, 10_000)
GLOBAL_RATE_WINDOW_SECONDS = env_int(
    "GLOBAL_RATE_WINDOW_SECONDS", 60, 1, 3600
)
CONTACT_RATE_LIMIT = env_int("CONTACT_RATE_LIMIT", 5, 1, 100)
CONTACT_RATE_WINDOW_SECONDS = env_int(
    "CONTACT_RATE_WINDOW_SECONDS", 600, 10, 86_400
)
RATE_LIMIT_MAX_CLIENTS = env_int(
    "RATE_LIMIT_MAX_CLIENTS", 10_000, 100, 100_000
)
TELEGRAM_MESSAGE_MAX_CHARS = 3900

IS_RENDER = env_bool("RENDER")
TRUST_CLOUDFLARE_IP = env_bool(
    "TRUST_CLOUDFLARE_IP",
    default=IS_RENDER,
)

trusted_hosts = {
    item.strip()
    for item in os.getenv("TRUSTED_HOSTS", "").split(",")
    if item.strip()
}
render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname:
    trusted_hosts.add(render_hostname)
if trusted_hosts:
    app.config["TRUSTED_HOSTS"] = sorted(trusted_hosts)

app.config.update(
    MAX_CONTENT_LENGTH=MAX_BODY_BYTES,
    MAX_FORM_MEMORY_SIZE=MAX_BODY_BYTES,
    MAX_FORM_PARTS=20,
)

CORS(
    app,
    resources={
        r"/api/contact": {
            "origins": sorted(ALLOWED_ORIGINS),
        }
    },
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    supports_credentials=False,
    max_age=600,
)


class SlidingWindowRateLimiter:
    """Thread-safe, bounded in-memory sliding-window limiter.

    One limiter is shared by all threads in this process. A distributed store
    is required before running more than one Gunicorn process or Render
    instance.
    """

    def __init__(self, limit, window_seconds, max_clients):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._events = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key, now=None):
        current_time = time.monotonic() if now is None else now
        cutoff = current_time - self.window_seconds

        with self._lock:
            queue = self._events.pop(key, deque())
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= self.limit:
                retry_after = max(
                    1,
                    math.ceil(self.window_seconds - (current_time - queue[0])),
                )
                self._events[key] = queue
                self._prune(current_time)
                return False, retry_after

            queue.append(current_time)
            self._events[key] = queue
            self._prune(current_time)
            return True, 0

    def _prune(self, current_time):
        cutoff = current_time - self.window_seconds

        # OrderedDict keeps least-recently-used clients first. Stop as soon as
        # the oldest remaining client is still active, avoiding an O(n) scan
        # on every request.
        while self._events:
            key = next(iter(self._events))
            queue = self._events[key]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if not queue:
                del self._events[key]
                continue
            break

        while len(self._events) > self.max_clients:
            self._events.popitem(last=False)

    def clear(self):
        with self._lock:
            self._events.clear()

    @property
    def client_count(self):
        with self._lock:
            return len(self._events)


global_limiter = SlidingWindowRateLimiter(
    GLOBAL_RATE_LIMIT,
    GLOBAL_RATE_WINDOW_SECONDS,
    RATE_LIMIT_MAX_CLIENTS,
)
contact_limiter = SlidingWindowRateLimiter(
    CONTACT_RATE_LIMIT,
    CONTACT_RATE_WINDOW_SECONDS,
    RATE_LIMIT_MAX_CLIENTS,
)


def normalized_ip(value):
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return ""


def client_ip():
    # Render sets RENDER=true and routes public traffic through Cloudflare.
    # CF-Connecting-IP is a single edge-generated address; arbitrary XFF
    # values from clients are deliberately ignored.
    if TRUST_CLOUDFLARE_IP:
        cloudflare_ip = normalized_ip(
            request.headers.get("CF-Connecting-IP", "")
        )
        if cloudflare_ip:
            return cloudflare_ip

    return normalized_ip(request.remote_addr) or "unknown"


def cf_ray():
    value = request.headers.get("CF-Ray", "").strip()
    if re.fullmatch(r"[A-Za-z0-9-]{1,80}", value):
        return value
    return "unavailable"


def clean(value, max_length, multiline=False):
    if value is None:
        return ""

    text = str(value).replace("\x00", "").replace("\r", "")
    if multiline:
        text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    else:
        text = " ".join(text.split())
    return text[:max_length]


def error_response(error, status, retry_after=None):
    response = jsonify({"ok": False, "error": error})
    response.status_code = status
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


@app.after_request
def add_security_headers(response):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=()"
    )
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, nosnippet"

    if IS_RENDER or request.is_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


@app.before_request
def apply_global_rate_limit():
    if request.path == "/healthz":
        return None

    allowed, retry_after = global_limiter.check(client_ip())
    if not allowed:
        return error_response("rate_limited", 429, retry_after)
    return None


@app.errorhandler(HTTPException)
def handle_http_error(error):
    names = {
        400: "bad_request",
        404: "not_found",
        405: "method_not_allowed",
        413: "payload_too_large",
    }
    return error_response(
        names.get(error.code, "request_error"),
        error.code or 500,
    )


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.error(
        "Unhandled application error type=%s ray=%s",
        type(error).__name__,
        cf_ray(),
    )
    return error_response("internal_error", 500)


@app.get("/")
def root():
    return jsonify({"ok": True}), 200


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


@app.post("/api/contact")
def contact():
    ip = client_ip()
    allowed, retry_after = contact_limiter.check(ip)
    if not allowed:
        return error_response("rate_limited", 429, retry_after)

    origin = request.headers.get("Origin", "").rstrip("/")
    if origin not in ALLOWED_ORIGINS:
        return error_response("origin_not_allowed", 403)

    if not request.is_json:
        return error_response("json_required", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("invalid_json", 400)

    # Honeypot. Настоящий посетитель это поле не видит.
    if clean(data.get("website"), 200):
        return jsonify({"ok": True}), 200

    form_type = clean(data.get("form_type"), 100)
    name = clean(data.get("name"), 120)
    email = clean(data.get("email"), 200)
    contact_value = clean(data.get("contact"), 200)
    link = clean(data.get("link"), 500)
    message = clean(data.get("message"), 3000, multiline=True)

    if not form_type or not message:
        return error_response("missing_fields", 400)

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
    telegram_text = "\n".join(lines)
    if len(telegram_text) > TELEGRAM_MESSAGE_MAX_CHARS:
        telegram_text = telegram_text[: TELEGRAM_MESSAGE_MAX_CHARS - 1] + "…"

    telegram_url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            telegram_url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": telegram_text,
                "disable_web_page_preview": True,
            },
            timeout=(3.05, 5),
        )
    except requests.RequestException as error:
        # Исключение Requests может содержать полный URL вместе с bot token.
        app.logger.warning(
            "Telegram request failed type=%s ray=%s",
            type(error).__name__,
            cf_ray(),
        )
        return error_response("telegram_unreachable", 502)

    if not response.ok:
        # Тело ответа не логируется: в нём могут быть внутренние данные.
        app.logger.error(
            "Telegram API error status=%s ray=%s",
            response.status_code,
            cf_ray(),
        )
        return error_response("telegram_error", 502)

    return jsonify({"ok": True}), 200
