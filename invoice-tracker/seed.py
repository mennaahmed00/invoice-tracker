"""Creates demo user demo@example.com / demo12345 with sample invoices."""
from datetime import date, timedelta
from app.main import conn, init_db, hash_pw

init_db()
with conn() as c:
    if c.execute("SELECT 1 FROM users WHERE email='demo@example.com'").fetchone():
        print("Already seeded"); raise SystemExit
    uid = c.execute("INSERT INTO users(email,password_hash) VALUES(?,?)",
                    ("demo@example.com", hash_pw("demo12345"))).lastrowid
    t = date.today()
    for client, amt, days, st in [("Acme Ltd", 1200, -20, "unpaid"), ("Globex", 450.5, -3, "unpaid"),
                                  ("Initech", 980, 10, "unpaid"), ("Umbrella", 300, -40, "paid"),
                                  ("Hooli", 2500, 25, "unpaid")]:
        c.execute("INSERT INTO invoices(user_id,client,amount_cents,due_date,status) VALUES(?,?,?,?,?)",
                  (uid, client, round(amt * 100), (t + timedelta(days=days)).isoformat(), st))
print("Seeded. Login: demo@example.com / demo12345")
