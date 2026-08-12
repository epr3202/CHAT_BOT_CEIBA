from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.admin.routes import require_admin_token


def make_client(admin_api_token: str) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(admin_api_token=admin_api_token)

    @app.get("/protected", dependencies=[Depends(require_admin_token)])
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_empty_admin_token_returns_503() -> None:
    with make_client("") as client:
        response = client.get("/protected", headers={"Authorization": "Bearer any"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Admin API token is not configured"


def test_missing_admin_header_returns_401() -> None:
    with make_client("expected-token") as client:
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_wrong_admin_token_returns_401() -> None:
    with make_client("expected-token") as client:
        response = client.get("/protected", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_correct_admin_token_passes() -> None:
    with make_client("expected-token") as client:
        response = client.get("/protected", headers={"Authorization": "Bearer expected-token"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
