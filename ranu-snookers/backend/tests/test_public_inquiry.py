from app.api.v1 import public as public_api


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
