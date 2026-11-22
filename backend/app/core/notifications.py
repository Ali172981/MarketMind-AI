from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.operations import diagnostics

logger = logging.getLogger(__name__)
_last_alerts: dict[str, float] = {}


def configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id) or bool(settings.smtp_host and settings.smtp_to and settings.smtp_from)


def _send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_from, settings.smtp_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_starttls:
            server.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


async def _send(message: str) -> None:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": message[:3900], "disable_web_page_preview": True})
                response.raise_for_status()
        except Exception:
            logger.exception("Telegram operational alert delivery failed")
    if settings.smtp_host and settings.smtp_to and settings.smtp_from:
        try:
            await asyncio.to_thread(_send_email, "MarketMind AI operational alert", message)
        except Exception:
            logger.exception("Email operational alert delivery failed")


async def monitor_loop() -> None:
    """Poll service diagnostics and send deduplicated alerts; never affects trading logic."""
    while True:
        try:
            report = diagnostics()
            problems = []
            for name, check in report["checks"].items():
                if check.get("status") in {"error", "warning"}:
                    problems.append(f"{name}: {check.get('status')}")
                if name == "market_data":
                    for pair in check.get("pairs", []):
                        if pair.get("status") in {"missing", "stale", "error"}:
                            problems.append(f"{pair['symbol']} {pair['interval']}: {pair['status']}")
            active = set(problems)
            now = asyncio.get_running_loop().time()
            for problem in problems:
                key = problem
                if now - _last_alerts.get(key, 0) >= max(60, settings.alert_cooldown_seconds):
                    await _send(f"MarketMind AI alert\n{problem}\nUTC: {datetime.now(timezone.utc).isoformat()}\nNo trading action was taken.")
                    _last_alerts[key] = now
            # Clear recovered alerts so a later recurrence can notify immediately.
            for key in list(_last_alerts):
                if key not in active:
                    _last_alerts.pop(key, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Operational monitoring cycle failed")
        await asyncio.sleep(max(30, settings.monitor_interval_seconds))
