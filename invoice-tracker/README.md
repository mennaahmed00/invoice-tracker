# Invoice Tracker — "Never chase an invoice by memory again"

A small backend for freelancers: log invoices, get automatically flagged when clients are late, and export a PDF report.

**10x claim:** Finding out which invoices are late and how much money is outstanding goes from ~10 minutes of scanning a spreadsheet to one API call (cached) or one PDF download.
**Non-goal:** No payment processing, no sending real emails, no frontend.

## Concepts used (6 of 7 — no swaps)

| # | Concept | Where it lives |
|---|---------|----------------|
| 1 | API endpoints (status codes + validation) | `app/main.py` — Pydantic models, 201/401/404/409/422 |
| 2 | Database (SQLite, survives restart) | `app/main.py` — `init_db()`, `conn()` |
| 3 | Authentication (JWT, protected routes) | `app/main.py` — `make_token`, `current_user` |
| 4 | Cron + background job | `overdue_check()`, scheduled daily 08:00; `POST /jobs/overdue-check` runs it via `BackgroundTasks` |
| 5 | Reporting — PDF | `GET /report.pdf` (reportlab) |
| 6 | Caching | `cached_summary()` — 60s TTL, invalidated on every write |

Bonus: test suite in `tests/`.

## Run it

```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then set SECRET_KEY (any long random string)
export $(cat .env | xargs)                           # Windows PowerShell: set the vars manually
python seed.py                                       # demo user + sample invoices
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs (interactive API docs).

Tests: `python -m pytest`

## 5-minute demo path

1. Open `/docs` → `POST /auth/login` with `demo@example.com` / `demo12345` → copy `access_token`.
2. Click **Authorize** (top right), paste the token.
3. `GET /summary` → see totals (`"cached": false`). Call again → `"cached": true`.
4. `POST /jobs/overdue-check` → then `GET /invoices?status=overdue` → late invoices were flagged.
5. `GET /report.pdf` → download the PDF report.
6. Try any route without authorizing → `401`.

## Future ideas
Real email reminders, multi-currency, a small web page.
