# My 10x Solution — Invoice Tracker

## 1. What is the problem?
Freelancers often track invoices in a spreadsheet or in their head. When a client pays late, nobody notices until the money is badly overdue, and working out "how much am I owed right now?" means manually scanning rows. This costs real money and mental energy. The people with this problem are freelancers and tiny agencies without accounting software.

**10x claim:** knowing what is overdue and what is owed goes from about 10 minutes of manual checking to one request (or one PDF download).

**Non-goal:** no payment processing, no real emails, no frontend.

## 2. How did I implement it?
It is a Python (FastAPI) backend with a SQLite database. A user registers and logs in, receives a JWT token, and uses it to create invoices, mark them paid, and view a summary. Every night at 08:00 a scheduled job finds unpaid invoices past their due date, marks them overdue and records a reminder. The same job can be triggered on demand through an endpoint and runs in the background so the request returns immediately. The summary of totals is cached for 60 seconds and the cache is cleared whenever data changes. A PDF report of all invoices can be downloaded.

**Concepts implemented (6, no swaps):**
1. API endpoints with validation and correct status codes
2. Database (SQLite, data persists)
3. Authentication (JWT, protected routes, per-user data isolation)
4. Background job + cron job (daily overdue check)
5. Reporting — PDF download
6. Caching (60s TTL summary, invalidated on writes)

Extra: automated tests for the risky cases (unauthenticated access, validation, cache behaviour, users accessing each other's data).

**How to run:**
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and set `SECRET_KEY`
3. `python seed.py`
4. `uvicorn app.main:app --reload`, then open http://127.0.0.1:8000/docs and log in with `demo@example.com` / `demo12345`

Full demo path is in the README.
