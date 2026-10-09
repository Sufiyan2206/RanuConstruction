"""Notification channel providers. Swap by env var — business code never knows
which vendor delivers the message."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.core.config import settings

log = logging.getLogger("app.notifications")


class ChannelProvider(Protocol):
    def send(self, recipient: str, subject: str | None, body: str) -> None: ...


class ConsoleProvider:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    def send(self, recipient, subject, body) -> None:
        log.info("notification", extra={"channel": self.channel, "to": recipient, "subject": subject, "body": body[:500]})


class SmtpEmailProvider:
    def send(self, recipient, subject, body) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, recipient, subject or settings.APP_NAME
        msg.set_content(body)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
            s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)


class HttpSmsProvider:
    """Generic JSON SMS gateway (MSG91 / Twilio-compatible adapters can subclass)."""

    def send(self, recipient, subject, body) -> None:
        r = httpx.post(settings.SMS_HTTP_URL, headers={"Authorization": f"Bearer {settings.SMS_API_KEY}"}, json={"to": recipient, "message": body}, timeout=15)
        r.raise_for_status()


class MetaWhatsAppProvider:
    """WhatsApp Cloud API (text message; production templates configurable)."""

    def send(self, recipient, subject, body) -> None:
        r = httpx.post(
            f"https://graph.facebook.com/v19.0/{settings.WHATSAPP_PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            json={"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": body}}, timeout=15,
        )
        r.raise_for_status()


def get_channel_provider(channel: str) -> ChannelProvider:
    if channel == "EMAIL" and settings.EMAIL_PROVIDER == "smtp":
        return SmtpEmailProvider()
    if channel == "SMS" and settings.SMS_PROVIDER == "http":
        return HttpSmsProvider()
    if channel == "WHATSAPP" and settings.WHATSAPP_PROVIDER == "meta":
        return MetaWhatsAppProvider()
    return ConsoleProvider(channel)  # PUSH: wire FCM/APNs here when the mobile app ships
