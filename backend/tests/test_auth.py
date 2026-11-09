from datetime import datetime, timedelta, timezone

import pytest

from app.models import OtpChallenge


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/me"),
        ("get", "/retailer/catalogue"),
        ("get", "/retailer/orders"),
        ("post", "/orders/preview"),
        ("post", "/ai/extract-text"),
        ("get", "/desk/orders"),
        ("post", "/desk/exports"),
    ],
)
def test_unauthenticated_requests_rejected(client, method, path):
    r = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


def test_garbage_token_rejected(client):
    r = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_otp_login_returns_role_from_server(client):
    r = client.post("/auth/request-otp", json={"identifier": "+91 90000 00009"})
    body = r.json()
    assert body["demo_mode"] is True and "123456" in body["demo_hint"]
    r = client.post("/auth/verify-otp", json={"challenge_id": body["challenge_id"], "otp": "123456"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "order_desk"


def test_otp_is_stored_hashed(client, db):
    r = client.post("/auth/request-otp", json={"identifier": "9000000001"})
    ch = db.get(OtpChallenge, r.json()["challenge_id"])
    assert ch is not None and "123456" not in ch.otp_hash and len(ch.otp_hash) == 64


def test_wrong_otp_then_lockout(client):
    cid = client.post("/auth/request-otp", json={"identifier": "9000000001"}).json()["challenge_id"]
    for _ in range(5):
        r = client.post("/auth/verify-otp", json={"challenge_id": cid, "otp": "000000"})
        assert r.status_code == 401
    r = client.post("/auth/verify-otp", json={"challenge_id": cid, "otp": "123456"})
    assert r.status_code == 429


def test_otp_cannot_be_reused(client):
    cid = client.post("/auth/request-otp", json={"identifier": "9000000001"}).json()["challenge_id"]
    assert client.post("/auth/verify-otp", json={"challenge_id": cid, "otp": "123456"}).status_code == 200
    r = client.post("/auth/verify-otp", json={"challenge_id": cid, "otp": "123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_expired"


def test_expired_otp_rejected(client, db):
    cid = client.post("/auth/request-otp", json={"identifier": "9000000001"}).json()["challenge_id"]
    ch = db.get(OtpChallenge, cid)
    ch.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    r = client.post("/auth/verify-otp", json={"challenge_id": cid, "otp": "123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_expired"


def test_unknown_identifier_gets_generic_response_and_cannot_log_in(client):
    r = client.post("/auth/request-otp", json={"identifier": "9999999999"})
    assert r.status_code == 200
    r = client.post("/auth/verify-otp", json={"challenge_id": r.json()["challenge_id"], "otp": "123456"})
    assert r.status_code == 401


def test_retailer_cannot_use_desk_endpoints(client, retailer_a):
    for method, path in [
        ("get", "/desk/orders"),
        ("get", "/desk/orders/1"),
        ("patch", "/desk/orders/1"),
        ("get", "/desk/exports/preview"),
        ("post", "/desk/exports"),
        ("get", "/desk/exports/1/download"),
        ("get", "/desk/aliases"),
    ]:
        kwargs = {"json": {"action": "approve", "version": 1}} if method in ("patch", "post") else {}
        r = getattr(client, method)(path, headers=retailer_a, **kwargs)
        assert r.status_code == 403, (method, path, r.text)


def test_desk_cannot_use_retailer_endpoints(client, desk):
    assert client.get("/retailer/catalogue", headers=desk).status_code == 403
    assert client.post("/ai/extract-text", headers=desk, json={"message": "5 case biscuit"}).status_code == 403
    r = client.post(
        "/orders", headers=desk, json={"client_request_id": "desk-attempt-1", "lines": [{"sku_code": "SKU-BS-075", "paid_qty": 1}]}
    )
    assert r.status_code == 403
