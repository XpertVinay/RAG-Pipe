"""Tests for PII Breach Alerting, Contextual Masking '(*****, [meaning of context])', Share Link Revocation, and Consent."""

import pytest
from httpx import AsyncClient

from app.services.pii_service import pii_service


def test_pii_contextual_masking():
    """Verify sensitive PII is masked with '(*****, [Context: meaning of the context])'."""
    text = (
        "Please email me at john.doe@acme-corp.com or call +1 415-555-2671. "
        "My OpenAI token is sk-12345678901234567890abcdef. "
        "The test card number is 4111 2222 3333 4444."
    )

    result = pii_service.scan_and_mask(text)
    assert result.has_pii is True
    assert result.breach_count >= 4
    assert result.risk_level in ("high", "critical")

    masked = result.masked_text
    # Verify contextual meaning is embedded inside the mask
    assert "(*****, [Email Context: personal contact email address detected])" in masked
    assert "(*****, [Phone Context: personal telephone contact number detected])" in masked
    assert "(*****, [Credential Context: sensitive API key, access token, or client secret detected])" in masked
    assert "(*****, [Financial Context: credit or debit payment card number detected])" in masked

    # Ensure raw PII is NOT present in masked text
    assert "john.doe@acme-corp.com" not in masked
    assert "sk-12345678901234567890abcdef" not in masked
    assert "4111 2222 3333 4444" not in masked


@pytest.mark.asyncio
async def test_room_share_link_generate_and_revoke(client: AsyncClient):
    """Verify room share link generation and immediate revocation locking out external access."""
    # 1. Create a Room
    room_res = await client.post(
        "/api/rooms",
        json={"name": "Confidential Finance Room", "description": "Budget docs for ceo@internal.corp"},
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    # 2. Generate Share Link
    gen_res = await client.post(f"/api/rooms/{room_id}/share-link/generate")
    assert gen_res.status_code == 200
    share_data = gen_res.json()
    assert share_data["is_public"] is True
    assert share_data["is_revoked"] is False
    assert "share_token" in share_data
    share_token = share_data["share_token"]

    # 3. Access shared room via token
    pub_res = await client.get(f"/api/rooms/shared/{share_token}")
    assert pub_res.status_code == 200
    # Description had email -> verify it is contextually masked
    assert "(*****, [Email Context:" in pub_res.json()["description"]

    # 4. Revoke the Share Link
    rev_res = await client.post(f"/api/rooms/{room_id}/share-link/revoke")
    assert rev_res.status_code == 200
    assert rev_res.json()["is_revoked"] is True

    # 5. Accessing shared link after revocation must return 410 GONE
    revoked_access_res = await client.get(f"/api/rooms/shared/{share_token}")
    assert revoked_access_res.status_code == 410


@pytest.mark.asyncio
async def test_room_pii_scan_and_consent(client: AsyncClient):
    """Verify PII scanning detects breaches and user consent capture."""
    # Create room
    r_res = await client.post(
        "/api/rooms",
        json={"name": "Client Onboarding", "description": "Contact info: client@bank.com"},
    )
    assert r_res.status_code == 201
    room_id = r_res.json()["id"]

    # Scan for PII
    scan_res = await client.post(f"/api/rooms/{room_id}/pii/scan")
    assert scan_res.status_code == 200
    scan_data = scan_res.json()
    assert scan_data["has_pii_breach"] is True
    assert "email" in scan_data["detected_categories"]
    assert scan_data["pii_consent_status"] == "breach_detected"

    # User consents to share with PII masked
    consent_res = await client.post(
        f"/api/rooms/{room_id}/pii/consent",
        json={"consent_mode": "mask", "confirm_acknowledgment": True},
    )
    assert consent_res.status_code == 200
    assert consent_res.json()["pii_consent_status"] == "consent_masked"
