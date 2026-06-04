from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.core import router


def test_root_redirects_to_platform():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == "/platform/"