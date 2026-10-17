from app.api.v1 import public as public_api
from app.notifications import providers


def test_interiors_inquiry_emails_all_submitted_fields(client, monkeypatch):
    sent = {}

    class EmailProvider:
        def send(self, recipient, subject, body):
            sent.update(recipient=recipient, subject=subject, body=body)

    monkeypatch.setattr(public_api.settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(public_api.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(public_api, "get_channel_provider", lambda channel: EmailProvider())

    response = client.post(
        "/api/v1/public/inquiries/interiors",
        json={
            "name": "Asha",
            "phone": "9876543210",
            "property_type": "2BHK",
            "scope": "Full interiors",
            "message": "Need a kitchen and bedroom design.",
        },
    )

    assert response.status_code == 202
    assert sent["recipient"] == "info@ranugroupindia.com"
    assert sent["subject"] == "New interiors consultation request"
    assert "Name: Asha" in sent["body"]
    assert "Phone: 9876543210" in sent["body"]
    assert "Property: 2BHK" in sent["body"]
    assert "Scope: Full interiors" in sent["body"]
    assert "Additional details: Need a kitchen and bedroom design." in sent["body"]


def test_interiors_inquiry_fails_when_email_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(public_api.settings, "EMAIL_PROVIDER", "console")

    response = client.post(
        "/api/v1/public/inquiries/interiors",
        json={
            "name": "Asha",
            "phone": "9876543210",
            "property_type": "2BHK",
            "scope": "Full interiors",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Email delivery is not configured."


def test_interiors_inquiry_rejects_blank_required_fields(client):
    response = client.post(
        "/api/v1/public/inquiries/interiors",
        json={
            "name": "   ",
            "phone": "9876543210",
            "property_type": "2BHK",
            "scope": "Full interiors",
        },
    )

    assert response.status_code == 422


def test_smtp_email_provider_uses_implicit_ssl(monkeypatch):
    sent = {}

    class SmtpConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            sent["starttls"] = True

        def login(self, username, password):
            sent["credentials"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    def smtp_ssl(host, port, timeout):
        sent["connection"] = (host, port, timeout)
        return SmtpConnection()

    monkeypatch.setattr(providers.settings, "SMTP_HOST", "smtpout.secureserver.net")
    monkeypatch.setattr(providers.settings, "SMTP_PORT", 465)
    monkeypatch.setattr(providers.settings, "SMTP_USE_SSL", True)
    monkeypatch.setattr(providers.settings, "SMTP_USER", "info@ranugroupindia.com")
    monkeypatch.setattr(providers.settings, "SMTP_PASSWORD", "test-mailbox-password")
    monkeypatch.setattr(providers.settings, "SMTP_FROM", "info@ranugroupindia.com")
    monkeypatch.setattr(providers.smtplib, "SMTP_SSL", smtp_ssl)

    providers.SmtpEmailProvider().send("info@ranugroupindia.com", "Test", "Body")

    assert sent["connection"] == ("smtpout.secureserver.net", 465, 15)
    assert sent["credentials"] == ("info@ranugroupindia.com", "test-mailbox-password")
    assert "starttls" not in sent
    assert sent["message"]["To"] == "info@ranugroupindia.com"


def test_smtp_email_provider_uses_starttls_when_ssl_is_disabled(monkeypatch):
    sent = {}

    class SmtpConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            sent["starttls"] = True

        def send_message(self, message):
            sent["message"] = message

    def smtp(host, port, timeout):
        sent["connection"] = (host, port, timeout)
        return SmtpConnection()

    monkeypatch.setattr(providers.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(providers.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(providers.settings, "SMTP_USE_SSL", False)
    monkeypatch.setattr(providers.settings, "SMTP_USER", "")
    monkeypatch.setattr(providers.smtplib, "SMTP", smtp)

    providers.SmtpEmailProvider().send("info@ranugroupindia.com", "Test", "Body")

    assert sent["connection"] == ("smtp.example.com", 587, 15)
    assert sent["starttls"] is True
