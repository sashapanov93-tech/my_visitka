# Portfolio Requests Backend

Small Flask API for securely forwarding portfolio contact-form submissions to Telegram.

## Render settings

Build command:

    pip install -r requirements.txt

Start command:

    gunicorn app:app

Health check path:

    /healthz

Environment variables:

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- ALLOWED_ORIGIN

`ALLOWED_ORIGIN` must be the exact public origin of your portfolio site, for example:

    https://my-visitka.onrender.com

Do not put the Telegram bot token into HTML or JavaScript.
