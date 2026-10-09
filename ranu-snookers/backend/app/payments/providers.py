"""Payment provider abstraction.

Booking/billing code only talks to ``PaymentProvider``. Adding a provider means
adding a class here and selecting it with ``PAYMENT_PROVIDER`` — no change to
business logic.

The provider webhook is the *authoritative* signal that money was received.
The browser redirect is only a UX hint (see PaymentService.handle_webhook).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.errors import AppError, Unauthorized


@dataclass
class CheckoutOrder:
    provider: str
    provider_order_id: str
    amount: Decimal
    currency: str
    # Everything the frontend needs to open the provider's checkout (public data only).
    client_payload: dict = field(default_factory=dict)


@dataclass
class WebhookResult:
    event_id: str
    event_type: str
    provider_order_id: str | None
    provider_payment_id: str | None
    status: str  # PAID | FAILED | REFUNDED | AUTHORIZED | IGNORED
    amount: Decimal | None
    raw: dict


class PaymentProvider(Protocol):
    name: str

    def create_order(self, *, amount: Decimal, currency: str, reference: str, customer: dict, metadata: dict) -> CheckoutOrder: ...

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookResult: ...

    def refund(self, *, provider_payment_id: str, amount: Decimal) -> str: ...


def _paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


class MockProvider:
    """Development / demo provider. Checkout happens on our own page; the
    "payment" is confirmed by a signed webhook exactly like a real provider."""

    name = "mock"

    def create_order(self, *, amount, currency, reference, customer, metadata) -> CheckoutOrder:
        oid = f"mock_order_{uuid.uuid4().hex[:18]}"
        return CheckoutOrder(self.name, oid, amount, currency, {"mode": "mock", "order_id": oid, "amount": str(amount), "currency": currency, "reference": reference})

    @staticmethod
    def sign(body: bytes) -> str:
        return hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    def verify_webhook(self, headers, body) -> WebhookResult:
        sig = headers.get("x-mock-signature", "")
        if not hmac.compare_digest(sig, self.sign(body)):
            raise Unauthorized("Invalid webhook signature", code="WEBHOOK_SIGNATURE")
        data = json.loads(body)
        return WebhookResult(
            event_id=data["event_id"], event_type=data.get("type", "payment.captured"), provider_order_id=data.get("order_id"),
            provider_payment_id=data.get("payment_id"), status=data.get("status", "PAID"),
            amount=Decimal(str(data["amount"])) if data.get("amount") is not None else None, raw=data,
        )

    def refund(self, *, provider_payment_id, amount) -> str:
        return f"mock_refund_{uuid.uuid4().hex[:12]}"


class RazorpayProvider:
    """Razorpay Orders API + webhook (X-Razorpay-Signature = HMAC-SHA256(body, webhook_secret))."""

    name = "razorpay"
    base = "https://api.razorpay.com/v1"

    def create_order(self, *, amount, currency, reference, customer, metadata) -> CheckoutOrder:
        resp = httpx.post(
            f"{self.base}/orders", auth=(settings.PAYMENT_KEY, settings.PAYMENT_SECRET), timeout=15,
            json={"amount": _paise(amount), "currency": currency, "receipt": reference, "notes": {k: str(v) for k, v in metadata.items()}},
        )
        if resp.status_code >= 300:
            raise AppError("Payment provider unavailable, please retry", code="PAYMENT_PROVIDER_ERROR", status_code=502)
        order = resp.json()
        return CheckoutOrder(self.name, order["id"], amount, currency, {
            "mode": "razorpay", "key": settings.PAYMENT_KEY, "order_id": order["id"], "amount": _paise(amount), "currency": currency,
            "name": settings.APP_NAME, "prefill": {"name": customer.get("name"), "contact": customer.get("phone"), "email": customer.get("email")},
        })

    def verify_webhook(self, headers, body) -> WebhookResult:
        sig = headers.get("x-razorpay-signature", "")
        expected = hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise Unauthorized("Invalid webhook signature", code="WEBHOOK_SIGNATURE")
        data = json.loads(body)
        event = data.get("event", "")
        ent = (data.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
        status = {"payment.captured": "PAID", "order.paid": "PAID", "payment.failed": "FAILED", "payment.authorized": "AUTHORIZED", "refund.processed": "REFUNDED"}.get(event, "IGNORED")
        return WebhookResult(
            event_id=headers.get("x-razorpay-event-id") or f"{event}:{ent.get('id')}", event_type=event,
            provider_order_id=ent.get("order_id"), provider_payment_id=ent.get("id"), status=status,
            amount=(Decimal(ent["amount"]) / 100) if ent.get("amount") is not None else None, raw=data,
        )

    def refund(self, *, provider_payment_id, amount) -> str:
        resp = httpx.post(f"{self.base}/payments/{provider_payment_id}/refund", auth=(settings.PAYMENT_KEY, settings.PAYMENT_SECRET), json={"amount": _paise(amount)}, timeout=15)
        if resp.status_code >= 300:
            raise AppError("Refund failed at provider", code="REFUND_FAILED", status_code=502)
        return resp.json()["id"]


class StripeProvider:
    """Stripe PaymentIntents + webhook (Stripe-Signature: t=..,v1=HMAC(t.body))."""

    name = "stripe"
    base = "https://api.stripe.com/v1"

    def create_order(self, *, amount, currency, reference, customer, metadata) -> CheckoutOrder:
        resp = httpx.post(
            f"{self.base}/payment_intents", auth=(settings.PAYMENT_SECRET, ""), timeout=15,
            data={"amount": _paise(amount), "currency": currency.lower(), "metadata[reference]": reference, "automatic_payment_methods[enabled]": "true"},
        )
        if resp.status_code >= 300:
            raise AppError("Payment provider unavailable, please retry", code="PAYMENT_PROVIDER_ERROR", status_code=502)
        pi = resp.json()
        return CheckoutOrder(self.name, pi["id"], amount, currency, {"mode": "stripe", "publishable_key": settings.PAYMENT_KEY, "client_secret": pi["client_secret"]})

    def verify_webhook(self, headers, body) -> WebhookResult:
        header = headers.get("stripe-signature", "")
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        ts = parts.get("t", "0")
        expected = hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(parts.get("v1", ""), expected) or abs(time.time() - int(ts)) > 300:
            raise Unauthorized("Invalid webhook signature", code="WEBHOOK_SIGNATURE")
        data = json.loads(body)
        obj = data.get("data", {}).get("object", {})
        status = {"payment_intent.succeeded": "PAID", "payment_intent.payment_failed": "FAILED", "charge.refunded": "REFUNDED"}.get(data.get("type"), "IGNORED")
        return WebhookResult(
            event_id=data["id"], event_type=data.get("type", ""), provider_order_id=obj.get("id") if obj.get("object") == "payment_intent" else obj.get("payment_intent"),
            provider_payment_id=obj.get("latest_charge") or obj.get("id"), status=status,
            amount=(Decimal(obj["amount"]) / 100) if obj.get("amount") is not None else None, raw=data,
        )

    def refund(self, *, provider_payment_id, amount) -> str:
        resp = httpx.post(f"{self.base}/refunds", auth=(settings.PAYMENT_SECRET, ""), data={"charge": provider_payment_id, "amount": _paise(amount)}, timeout=15)
        if resp.status_code >= 300:
            raise AppError("Refund failed at provider", code="REFUND_FAILED", status_code=502)
        return resp.json()["id"]


_PROVIDERS = {"mock": MockProvider, "razorpay": RazorpayProvider, "stripe": StripeProvider}


def get_provider(name: str | None = None) -> PaymentProvider:
    key = (name or settings.PAYMENT_PROVIDER).lower()
    if key not in _PROVIDERS:
        raise AppError(f"Unknown payment provider '{key}'", code="PAYMENT_PROVIDER_UNKNOWN", status_code=500)
    return _PROVIDERS[key]()
