import hashlib, hmac, io, os, secrets, sqlite3, time
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone

import jwt
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)  # never hardcoded
CACHE_TTL = 60  # seconds


def db_path():
    return os.getenv("DB_PATH", "invoices.db")


@contextmanager
def conn():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invoices(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, client TEXT NOT NULL,
          amount_cents INTEGER NOT NULL, due_date TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'unpaid');
        CREATE TABLE IF NOT EXISTS reminders(
          id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, created_at TEXT NOT NULL);
        """)


# ---------- Concept 3: authentication ----------
def hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return salt.hex() + ":" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    salt_hex, _ = stored.split(":")
    return hmac.compare_digest(hash_pw(pw, bytes.fromhex(salt_hex)), stored)


def make_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode({"sub": str(user_id), "exp": exp}, SECRET_KEY, algorithm="HS256")


bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> int:
    if not creds:
        raise HTTPException(401, "Missing token")
    try:
        return int(jwt.decode(creds.credentials, SECRET_KEY, algorithms=["HS256"])["sub"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


# ---------- Concept 6: caching ----------
_cache: dict[int, tuple[float, dict]] = {}


def invalidate(user_id: int):
    _cache.pop(user_id, None)


def compute_summary(user_id: int) -> dict:
    with conn() as c:
        rows = c.execute("SELECT status, COUNT(*) n, SUM(amount_cents) total FROM invoices "
                         "WHERE user_id=? GROUP BY status", (user_id,)).fetchall()
    out = {s: {"count": 0, "total": 0.0} for s in ("paid", "unpaid", "overdue")}
    for r in rows:
        out[r["status"]] = {"count": r["n"], "total": (r["total"] or 0) / 100}
    return out


def cached_summary(user_id: int) -> dict:
    hit = _cache.get(user_id)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}
    data = compute_summary(user_id)
    _cache[user_id] = (time.time(), data)
    return {**data, "cached": False}


# ---------- Concept 4: background / cron job ----------
def overdue_check():
    today = date.today().isoformat()
    with conn() as c:
        late = c.execute("SELECT id, user_id FROM invoices WHERE status='unpaid' AND due_date < ?",
                         (today,)).fetchall()
        for r in late:
            c.execute("UPDATE invoices SET status='overdue' WHERE id=?", (r["id"],))
            c.execute("INSERT INTO reminders(invoice_id, created_at) VALUES(?,?)",
                      (r["id"], datetime.now(timezone.utc).isoformat()))
    for r in late:
        invalidate(r["user_id"])
    return len(late)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = BackgroundScheduler()
    sched.add_job(overdue_check, "cron", hour=8, minute=0)  # every day at 08:00
    sched.start()
    yield
    sched.shutdown(wait=False)


app = FastAPI(title="Invoice Tracker", lifespan=lifespan)


# ---------- Concept 1: API endpoints with validation ----------
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class InvoiceIn(BaseModel):
    client: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    due_date: date


@app.post("/auth/register", status_code=201)
def register(body: Credentials):
    try:
        with conn() as c:
            c.execute("INSERT INTO users(email, password_hash) VALUES(?,?)",
                      (body.email.lower(), hash_pw(body.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email already registered")
    return {"message": "registered"}


@app.post("/auth/login")
def login(body: Credentials):
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (body.email.lower(),)).fetchone()
    if not u or not check_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return {"access_token": make_token(u["id"]), "token_type": "bearer"}


@app.post("/invoices", status_code=201)
def create_invoice(body: InvoiceIn, uid: int = Depends(current_user)):
    with conn() as c:
        cur = c.execute("INSERT INTO invoices(user_id, client, amount_cents, due_date) VALUES(?,?,?,?)",
                        (uid, body.client, round(body.amount * 100), body.due_date.isoformat()))
    invalidate(uid)
    return {"id": cur.lastrowid}


@app.get("/invoices")
def list_invoices(status: str | None = None, uid: int = Depends(current_user)):
    q, args = "SELECT * FROM invoices WHERE user_id=?", [uid]
    if status:
        if status not in ("paid", "unpaid", "overdue"):
            raise HTTPException(422, "status must be paid, unpaid or overdue")
        q += " AND status=?"
        args.append(status)
    with conn() as c:
        rows = c.execute(q + " ORDER BY due_date", args).fetchall()
    return [{**dict(r), "amount": r["amount_cents"] / 100} for r in rows]


@app.patch("/invoices/{invoice_id}/pay")
def mark_paid(invoice_id: int, uid: int = Depends(current_user)):
    with conn() as c:
        cur = c.execute("UPDATE invoices SET status='paid' WHERE id=? AND user_id=?", (invoice_id, uid))
    if cur.rowcount == 0:
        raise HTTPException(404, "Invoice not found")
    invalidate(uid)
    return {"message": "paid"}


@app.get("/summary")
def summary(uid: int = Depends(current_user)):
    return cached_summary(uid)


@app.post("/jobs/overdue-check", status_code=202)
def trigger_overdue(bg: BackgroundTasks, uid: int = Depends(current_user)):
    bg.add_task(overdue_check)  # slow work off the request path
    return {"message": "overdue check started"}


# ---------- Concept 5: PDF report ----------
@app.get("/report.pdf")
def report(uid: int = Depends(current_user)):
    invoices = list_invoices(None, uid)
    s = compute_summary(uid)
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    y = 800
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, f"Invoice report - {date.today().isoformat()}")
    y -= 30
    p.setFont("Helvetica", 11)
    for k, v in s.items():
        p.drawString(50, y, f"{k.capitalize()}: {v['count']} invoices, {v['total']:.2f}")
        y -= 18
    y -= 15
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Client            Amount        Due          Status")
    p.setFont("Helvetica", 11)
    for i in invoices:
        y -= 18
        if y < 60:
            p.showPage(); y = 800; p.setFont("Helvetica", 11)
        p.drawString(50, y, f"{i['client'][:16]:<16}  {i['amount']:>9.2f}   {i['due_date']}   {i['status']}")
    p.save()
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=report.pdf"})
