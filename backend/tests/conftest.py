import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_STORAGE = Path("./test-storage")
TEST_DB = Path("./test-wikitics.db")

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["LOCAL_STORAGE_ROOT"] = str(TEST_STORAGE)
os.environ["VECTOR_BACKEND"] = "local"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["CORS_ORIGINS"] = "http://testserver"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["SARVAM_API_KEY"] = ""

from app.infrastructure.db.models import Base
from app.infrastructure.db.session import engine
from app.main import app


@pytest.fixture()
def client():
    yield from _test_client()


@pytest.fixture()
def non_raising_client():
    yield from _test_client(raise_server_exceptions=False)


def _test_client(raise_server_exceptions: bool = True):
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
    if TEST_STORAGE.exists():
        shutil.rmtree(TEST_STORAGE)
    if hasattr(app.state, "vector_search"):
        delattr(app.state, "vector_search")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app, raise_server_exceptions=raise_server_exceptions) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
    if TEST_STORAGE.exists():
        shutil.rmtree(TEST_STORAGE)


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "password123", "name": "Owner"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def workspace_id(client, auth_headers):
    response = client.get("/api/workspaces", headers=auth_headers)
    assert response.status_code == 200
    return response.json()[0]["id"]
