"""Automated tests for creating application project requests with client details, communication channels, and initiating calls with conversation transcripts."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_app_creation_request_with_transcripts_and_call_initiation(client: AsyncClient):
    """Verify that prompting an application creation request registers on projects table with client details (Name, Email, Phone, Channel) and initiates call with transcripts."""
    # 1. Create a workspace room
    room_res = await client.post(
        "/api/rooms",
        json={"name": "HealthTech Innovation Lab", "description": "Healthcare digital transformation workspace"},
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    # 2. Create a conversation thread and add messages
    chat_res = await client.post(
        f"/api/chat/conversations?title=Telemedicine%20App%20Discussion&room_id={room_id}"
    )
    assert chat_res.status_code == 201
    conv_id = chat_res.json()["id"]

    # Post user prompt inquiring to build an application
    query_payload = {
        "message": "I want to create a HIPAA compliant telemedicine mobile application with video calls and appointment scheduling.",
        "conversation_id": conv_id,
        "room_id": room_id,
    }
    user_msg_res = await client.post("/api/chat/query", json=query_payload)
    assert user_msg_res.status_code == 200
    msg_data = user_msg_res.json()
    assert msg_data["metadata_info"].get("is_app_creation") is True
    assert msg_data["metadata_info"].get("response_type") == "app_creation"

    # 3. Create an application project request on the projects table
    app_req_payload = {
        "name": "Telemedicine Mobile Application",
        "description": "HIPAA compliant telemedicine platform with video consultations and appointment scheduling.",
        "client_name": "Dr. Sarah Jenkins",
        "email": "sarah.jenkins@healthtech.org",
        "phone": "+1 (555) 234-5678",
        "communication_channel": "Zoom",
        "room_id": room_id,
        "conversation_id": conv_id,
        "tags": ["healthcare", "zoom", "telemedicine", "app-request"],
    }

    create_proj_res = await client.post("/api/projects/app-request", json=app_req_payload)
    assert create_proj_res.status_code == 201
    project = create_proj_res.json()

    # Validate project details saved in projects table
    assert project["name"] == "Telemedicine Mobile Application"
    assert project["client_name"] == "Dr. Sarah Jenkins"
    assert project["email"] == "sarah.jenkins@healthtech.org"
    assert project["phone"] == "+1 (555) 234-5678"
    assert project["communication_channel"] == "Zoom"
    assert project["request_type"] == "app_creation"
    assert project["status"] == "pending_call"
    assert "https://zoom.us" in project["meeting_link"]

    # Validate transcripts compiled from conversation
    assert project["transcripts"] is not None
    assert "CONVERSATION TRANSCRIPT" in project["transcripts"]
    assert "telemedicine" in project["transcripts"].lower()

    project_id = project["id"]

    # 4. Initiate Call on the project - verify it returns transcripts and updates status
    call_res = await client.post(
        f"/api/projects/{project_id}/initiate-call",
        json={"communication_channel": "Zoom", "call_notes": "Initial requirements scoping meeting"},
    )
    assert call_res.status_code == 200
    call_data = call_res.json()

    assert call_data["project_id"] == project_id
    assert call_data["client_name"] == "Dr. Sarah Jenkins"
    assert call_data["email"] == "sarah.jenkins@healthtech.org"
    assert call_data["phone"] == "+1 (555) 234-5678"
    assert call_data["communication_channel"] == "Zoom"
    assert call_data["status"] == "call_initiated"
    assert call_data["call_initiated_at"] is not None
    assert "https://zoom.us" in call_data["meeting_link"]

    # Verify transcripts are present in call initiation
    assert call_data["transcripts"] is not None
    assert "sarah" in call_data["client_name"].lower()
    assert "telemedicine" in call_data["transcripts"].lower()

    # 5. Fetch project transcripts directly
    transcripts_res = await client.get(f"/api/projects/{project_id}/transcripts")
    assert transcripts_res.status_code == 200
    t_data = transcripts_res.json()
    assert t_data["project_id"] == project_id
    assert "CONVERSATION TRANSCRIPT" in t_data["transcripts"]
    assert t_data["client_name"] == "Dr. Sarah Jenkins"
    assert t_data["communication_channel"] == "Zoom"

    # 6. Verify room items list returns app creation metadata
    items_res = await client.get(f"/api/rooms/{room_id}/items?filter_type=projects")
    assert items_res.status_code == 200
    items_data = items_res.json()
    proj_item = next((i for i in items_data["items"] if i["id"] == project_id), None)
    assert proj_item is not None
    assert proj_item["request_type"] == "app_creation"
    assert proj_item["communication_channel"] == "Zoom"
    assert proj_item["client_name"] == "Dr. Sarah Jenkins"


@pytest.mark.asyncio
async def test_communication_channel_options(client: AsyncClient):
    """Verify various communication channels: Gmeet, Teams, Zoom, others."""
    channels = ["Gmeet", "Teams", "Zoom", "others"]
    for ch in channels:
        payload = {
            "name": f"{ch} Enterprise CRM",
            "client_name": f"Client for {ch}",
            "email": f"client_{ch.lower()}@domain.com",
            "phone": "+1 (555) 999-0000",
            "communication_channel": ch,
        }
        res = await client.post("/api/projects/app-request", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["communication_channel"] == ch

        # Initiate call
        call_res = await client.post(f"/api/projects/{data['id']}/initiate-call")
        assert call_res.status_code == 200
        c_data = call_res.json()
        assert c_data["communication_channel"] == ch
        assert c_data["status"] == "call_initiated"
        assert c_data["transcripts"] is not None
