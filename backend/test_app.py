import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import requests


os.environ["TELEGRAM_BOT_TOKEN"] = "unit-test-token"
os.environ["TELEGRAM_CHAT_ID"] = "unit-test-chat"
os.environ["ALLOWED_ORIGINS"] = "https://portfolio.example"
os.environ["TRUSTED_HOSTS"] = "localhost"
os.environ["RENDER"] = "true"

import app as app_module  # noqa: E402


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_storage_is_bounded_and_stale_clients_are_removed(self):
        limiter = app_module.SlidingWindowRateLimiter(
            limit=5,
            window_seconds=10,
            max_clients=3,
        )

        for index in range(5):
            allowed, _ = limiter.check(f"client-{index}", now=0)
            self.assertTrue(allowed)

        self.assertEqual(limiter.client_count, 3)

        allowed, _ = limiter.check("fresh-client", now=11)
        self.assertTrue(allowed)
        self.assertEqual(limiter.client_count, 1)

    def test_parallel_requests_cannot_bypass_limit(self):
        limiter = app_module.SlidingWindowRateLimiter(
            limit=5,
            window_seconds=60,
            max_clients=100,
        )

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(
                executor.map(
                    lambda _: limiter.check("same-client", now=1)[0],
                    range(6),
                )
            )

        self.assertEqual(sum(results), 5)


class ContactApiTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        app_module.global_limiter.clear()
        app_module.contact_limiter.clear()
        self.client = app_module.app.test_client()
        self.payload = {
            "form_type": "Website development request",
            "name": "Test User",
            "email": "visitor@example.test",
            "contact": "@visitor",
            "link": "https://example.test/project",
            "message": "Please build a small website.",
            "website": "",
        }

    def headers(self, ip="203.0.113.10", origin="https://portfolio.example"):
        return {
            "Origin": origin,
            "CF-Connecting-IP": ip,
            "CF-Ray": "test-ray-FRA",
        }

    def assert_security_headers(self, response):
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
        self.assertIn("max-age=31536000", response.headers["Strict-Transport-Security"])

    def test_health_is_read_only_and_not_rate_limited(self):
        for _ in range(150):
            response = self.client.get("/healthz")
            self.assertEqual(response.status_code, 200)

        self.assertEqual(app_module.global_limiter.client_count, 0)
        self.assertEqual(app_module.contact_limiter.client_count, 0)
        self.assert_security_headers(response)

    @patch("app.requests.post")
    def test_valid_submission_uses_safe_timeout_and_cors(self, post):
        post.return_value = Mock(ok=True, status_code=200)

        response = self.client.post(
            "/api/contact",
            json=self.payload,
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "https://portfolio.example",
        )
        self.assertEqual(post.call_args.kwargs["timeout"], (3.05, 5))
        self.assertLessEqual(
            len(post.call_args.kwargs["json"]["text"]),
            app_module.TELEGRAM_MESSAGE_MAX_CHARS,
        )
        self.assert_security_headers(response)

    @patch("app.requests.post")
    def test_missing_and_foreign_origins_are_rejected(self, post):
        missing = self.client.post(
            "/api/contact",
            json=self.payload,
            headers={"CF-Connecting-IP": "203.0.113.11"},
        )
        foreign = self.client.post(
            "/api/contact",
            json=self.payload,
            headers=self.headers(
                ip="203.0.113.12",
                origin="https://attacker.example",
            ),
        )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(foreign.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", foreign.headers)
        post.assert_not_called()
        self.assert_security_headers(foreign)

    @patch("app.requests.post")
    def test_spoofed_x_forwarded_for_cannot_bypass_limit(self, post):
        payload = dict(self.payload, website="filled-by-bot")
        responses = []

        for index in range(6):
            headers = self.headers(ip="203.0.113.20")
            headers["X-Forwarded-For"] = f"198.51.100.{index}"
            responses.append(
                self.client.post(
                    "/api/contact",
                    json=payload,
                    headers=headers,
                )
            )

        self.assertEqual([item.status_code for item in responses[:5]], [200] * 5)
        self.assertEqual(responses[5].status_code, 429)
        self.assertEqual(responses[5].get_json()["error"], "rate_limited")
        self.assertGreaterEqual(int(responses[5].headers["Retry-After"]), 1)
        post.assert_not_called()
        self.assert_security_headers(responses[5])

    @patch("app.requests.post")
    def test_missing_cloudflare_ip_falls_back_instead_of_trusting_xff(self, post):
        payload = dict(self.payload, website="filled-by-bot")
        statuses = []

        for index in range(6):
            statuses.append(
                self.client.post(
                    "/api/contact",
                    json=payload,
                    headers={
                        "Origin": "https://portfolio.example",
                        "X-Forwarded-For": f"198.51.100.{index}",
                    },
                ).status_code
            )

        self.assertEqual(statuses, [200, 200, 200, 200, 200, 429])
        post.assert_not_called()

    @patch("app.requests.post")
    def test_oversized_body_is_rejected_before_telegram(self, post):
        oversized = b'{"message":"' + (b"a" * app_module.MAX_BODY_BYTES) + b'"}'

        response = self.client.post(
            "/api/contact",
            data=oversized,
            content_type="application/json",
            headers=self.headers(ip="203.0.113.30"),
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"], "payload_too_large")
        post.assert_not_called()
        self.assert_security_headers(response)

    @patch("app.requests.post")
    def test_non_object_json_is_a_client_error(self, post):
        for index, value in enumerate((["item"], "text", 42)):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/contact",
                    json=value,
                    headers=self.headers(ip=f"203.0.113.{40 + index}"),
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"], "invalid_json")

        post.assert_not_called()

    @patch("app.requests.post")
    def test_honeypot_returns_success_without_telegram(self, post):
        response = self.client.post(
            "/api/contact",
            json=dict(self.payload, website="spam.example"),
            headers=self.headers(ip="203.0.113.50"),
        )

        self.assertEqual(response.status_code, 200)
        post.assert_not_called()

    @patch("app.requests.post")
    def test_network_exception_does_not_leak_secret_or_personal_data(self, post):
        sensitive_message = "private-message-marker"
        sensitive_email = "private-person@example.test"
        payload = dict(
            self.payload,
            email=sensitive_email,
            message=sensitive_message,
        )
        post.side_effect = requests.Timeout(
            "https://api.telegram.org/botunit-test-token/sendMessage"
        )

        with self.assertLogs(app_module.app.logger, level="WARNING") as logs:
            response = self.client.post(
                "/api/contact",
                json=payload,
                headers=self.headers(ip="203.0.113.60"),
            )

        output = "\n".join(logs.output)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("unit-test-token", output)
        self.assertNotIn("api.telegram.org", output)
        self.assertNotIn(sensitive_email, output)
        self.assertNotIn(sensitive_message, output)
        self.assert_security_headers(response)

    @patch("app.requests.post")
    def test_telegram_error_body_is_not_logged(self, post):
        response_body = "secret-upstream-response-marker"
        post.return_value = Mock(ok=False, status_code=429, text=response_body)

        with self.assertLogs(app_module.app.logger, level="ERROR") as logs:
            response = self.client.post(
                "/api/contact",
                json=self.payload,
                headers=self.headers(ip="203.0.113.70"),
            )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn(response_body, "\n".join(logs.output))

    @patch("app.requests.post")
    def test_telegram_message_is_capped(self, post):
        post.return_value = Mock(ok=True, status_code=200)
        payload = {
            "form_type": "f" * 100,
            "name": "n" * 120,
            "email": "e" * 200,
            "contact": "c" * 200,
            "link": "l" * 500,
            "message": "m" * 3000,
            "website": "",
        }

        response = self.client.post(
            "/api/contact",
            json=payload,
            headers=self.headers(ip="203.0.113.80"),
        )

        self.assertEqual(response.status_code, 200)
        telegram_text = post.call_args.kwargs["json"]["text"]
        self.assertEqual(len(telegram_text), app_module.TELEGRAM_MESSAGE_MAX_CHARS)
        self.assertTrue(telegram_text.endswith("…"))

    def test_untrusted_host_receives_generic_json_error(self):
        response = self.client.get(
            "/",
            headers={"Host": "attacker.example"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "bad_request")
        self.assert_security_headers(response)


if __name__ == "__main__":
    unittest.main()
