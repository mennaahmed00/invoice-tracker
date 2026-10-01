import os, tempfile
from datetime import date, timedelta
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
from app.main import app  # noqa: E402


def token(c, email):
    c.post("/auth/register", json={"email": email, "password": "password123"})
    t = c.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": "Bearer " + t}


def test_protected_route_needs_token():
    with TestClient(app) as c:
        assert c.get("/invoices").status_code == 401
        assert c.get("/invoices", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_validation_and_duplicate_register():
    with TestClient(app) as c:
        assert c.post("/auth/register", json={"email": "bad", "password": "x"}).status_code == 422
        body = {"email": "d@example.com", "password": "password123"}
        assert c.post("/auth/register", json=body).status_code == 201
        assert c.post("/auth/register", json=body).status_code == 409


def test_invoice_flow_cache_overdue_pdf():
    with TestClient(app) as c:
        h = token(c, "flow@example.com")
        past = (date.today() - timedelta(days=5)).isoformat()
        assert c.post("/invoices", json={"client": "X", "amount": -5, "due_date": past}, headers=h).status_code == 422
        iid = c.post("/invoices", json={"client": "X", "amount": 100, "due_date": past}, headers=h).json()["id"]
        assert c.get("/summary", headers=h).json()["cached"] is False
        assert c.get("/summary", headers=h).json()["cached"] is True
        c.post("/jobs/overdue-check", headers=h)
        assert c.get("/summary", headers=h).json()["overdue"]["count"] == 1
        assert c.get("/report.pdf", headers=h).content.startswith(b"%PDF")
        assert c.patch(f"/invoices/{iid}/pay", headers=h).status_code == 200


def test_users_cannot_touch_each_others_invoices():
    with TestClient(app) as c:
        h1, h2 = token(c, "u1@example.com"), token(c, "u2@example.com")
        iid = c.post("/invoices", json={"client": "X", "amount": 1, "due_date": "2030-01-01"}, headers=h1).json()["id"]
        assert c.patch(f"/invoices/{iid}/pay", headers=h2).status_code == 404
