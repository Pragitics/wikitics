import pytest
from fastapi import HTTPException

from app.adapters.repositories.sqlalchemy_repositories import SQLAlchemyUserRepository, SQLAlchemyWorkspaceRepository
from app.application.workspaces.access import ensure_workspace_member
from app.infrastructure.db.session import SessionLocal


def test_sqlalchemy_repositories_return_domain_entities(client):
    registered = client.post(
        "/api/auth/register",
        json={"email": "repo@example.com", "password": "password123", "name": "Repo User"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    workspace_id = client.get("/api/workspaces", headers=headers).json()[0]["id"]

    db = SessionLocal()
    try:
        user_repo = SQLAlchemyUserRepository(db)
        workspace_repo = SQLAlchemyWorkspaceRepository(db)

        user = user_repo.get_by_email("repo@example.com")
        workspace = workspace_repo.get(workspace_id)
        membership = workspace_repo.membership(user_id, workspace_id)
    finally:
        db.close()

    assert user and user.email == "repo@example.com"
    assert workspace and workspace.owner_id == user_id
    assert membership and membership.role == "owner"


def test_workspace_access_allows_members_and_rejects_non_members(client):
    owner = client.post(
        "/api/auth/register",
        json={"email": "access-owner@example.com", "password": "password123", "name": "Owner"},
    )
    owner_headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
    owner_user_id = client.get("/api/auth/me", headers=owner_headers).json()["id"]
    workspace_id = client.get("/api/workspaces", headers=owner_headers).json()[0]["id"]

    other = client.post(
        "/api/auth/register",
        json={"email": "access-other@example.com", "password": "password123", "name": "Other"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    other_user_id = client.get("/api/auth/me", headers=other_headers).json()["id"]

    db = SessionLocal()
    try:
        ensure_workspace_member(db, owner_user_id, workspace_id)
        with pytest.raises(HTTPException) as exc_info:
            ensure_workspace_member(db, other_user_id, workspace_id)
    finally:
        db.close()

    assert exc_info.value.status_code == 403
