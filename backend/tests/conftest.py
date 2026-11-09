"""Test setup.

Runs against SQLite by default (zero setup). Set TEST_DATABASE_URL to a
PostgreSQL URL to run the same suite — including the concurrency test — on
Postgres, e.g.:
    TEST_DATABASE_URL=postgresql+psycopg://fmcg:fmcg@localhost:5432/fmcg_test pytest
"""

import os
import pathlib

_DEFAULT_DB = f"sqlite:///{pathlib.Path(__file__).parent / '.pytest-fmcg.sqlite'}"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _DEFAULT_DB)
os.environ["APP_ENV"] = "test"
os.environ["DEMO_MODE"] = "true"
os.environ["DEMO_OTP"] = "123456"
os.environ["AI_PROVIDER_API_KEY"] = ""  # tests opt in to the LLM path explicitly (mocked)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

IS_POSTGRES = engine.url.get_backend_name() == "postgresql"

SAMPLE = "bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, chai patti 250 wala 1 peti"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def settings():
    return get_settings()


def login(client: TestClient, identifier: str) -> dict:
    r = client.post("/auth/request-otp", json={"identifier": identifier})
    assert r.status_code == 200, r.text
    r = client.post("/auth/verify-otp", json={"challenge_id": r.json()["challenge_id"], "otp": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def retailer_a(client):
    return login(client, "9000000001")


@pytest.fixture
def retailer_b(client):
    return login(client, "9000000002")


@pytest.fixture
def desk(client):
    return login(client, "9000000009")
