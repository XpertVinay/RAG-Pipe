"""Tests for Room > Projects and Chats hierarchy and polymorphic item listing."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_room_projects_crud_and_item_filtering(client: AsyncClient):
    """Verify creating projects in a room, linking chats to projects, and filtering room items."""
    # 1. Create a Room
    room_res = await client.post(
        "/api/rooms",
        json={"name": "Engineering Workspace", "description": "Core software initiatives"},
    )
    assert room_res.status_code == 201
    room_id = room_res.json()["id"]

    # 2. Create Project A in Room
    p1_res = await client.post(
        f"/api/rooms/{room_id}/projects",
        json={
            "name": "Backend Refactor",
            "description": "Async pipeline optimization",
            "status": "active",
            "tags": ["python", "architecture"],
        },
    )
    assert p1_res.status_code == 201
    p1 = p1_res.json()
    assert p1["name"] == "Backend Refactor"
    assert p1["room_id"] == room_id
    project_id = p1["id"]

    # 3. Create Project B in Room
    p2_res = await client.post(
        f"/api/rooms/{room_id}/projects",
        json={"name": "Frontend Design System", "status": "in_progress", "tags": ["css"]},
    )
    assert p2_res.status_code == 201

    # 4. Create Chat associated with Room & Project A
    chat1_res = await client.post(
        f"/api/chat/conversations?title=Refactor%20Discussion&room_id={room_id}&project_id={project_id}"
    )
    assert chat1_res.status_code == 201
    chat1 = chat1_res.json()
    assert chat1["room_id"] == room_id
    assert chat1["project_id"] == project_id

    # 5. Create Standalone Chat in Room (not tied to any project)
    chat2_res = await client.post(
        f"/api/chat/conversations?title=General%20Room%20Chat&room_id={room_id}"
    )
    assert chat2_res.status_code == 201

    # 6. Test Filtering: All Items
    all_res = await client.get(f"/api/rooms/{room_id}/items?filter_type=all")
    assert all_res.status_code == 200
    all_data = all_res.json()
    assert all_data["filter_type"] == "all"
    assert all_data["total_projects"] == 2
    assert all_data["total_chats"] == 2
    assert len(all_data["items"]) == 4

    # 7. Test Filtering: Only Projects
    proj_res = await client.get(f"/api/rooms/{room_id}/items?filter_type=projects")
    assert proj_res.status_code == 200
    proj_data = proj_res.json()
    assert proj_data["filter_type"] == "projects"
    assert len(proj_data["items"]) == 2
    assert all(item["item_type"] == "project" for item in proj_data["items"])

    # 8. Test Filtering: Only Chats
    chat_filter_res = await client.get(f"/api/rooms/{room_id}/items?filter_type=chats")
    assert chat_filter_res.status_code == 200
    chat_filter_data = chat_filter_res.json()
    assert chat_filter_data["filter_type"] == "chats"
    assert len(chat_filter_data["items"]) == 2
    assert all(item["item_type"] == "chat" for item in chat_filter_data["items"])

    # 9. Update Project A
    update_res = await client.put(
        f"/api/rooms/{room_id}/projects/{project_id}",
        json={"name": "Backend Refactor v2", "status": "completed"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Backend Refactor v2"
    assert update_res.json()["status"] == "completed"

    # 10. Delete Project A
    del_res = await client.delete(f"/api/rooms/{room_id}/projects/{project_id}")
    assert del_res.status_code == 200

    # Verify project is gone
    list_after = await client.get(f"/api/rooms/{room_id}/projects")
    assert len(list_after.json()) == 1
