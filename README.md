# CallUSSD Backend (Python Flask)

REST API for the CallUSSD iPhone app. Handles contact backup, call log, and USSD catalog.

## Quick Deploy on Render (Free Tier)

1. Push this folder to a GitHub repository.
2. Go to **render.com** → **New +** → **Web Service** → connect your repo.
3. Fill the dashboard:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
4. Add Environment Variables (see `.env.example`):
   - `SECRET_KEY` = long random string
   - `CORS_ORIGINS` = your frontend URL (or `*`)
   - `FLASK_ENV` = `production`
   - `DATABASE_URL` = leave blank for SQLite, or paste a Render Postgres URL
5. Click **Create Web Service**. Wait ~2 minutes.
6. Copy the `https://your-app.onrender.com` URL into the app → Guide tab → Backend URL.

## Run Locally

```bash
pip install -r requirements.txt
cp .env.example .env   # edit values
python app.py
# API at http://localhost:5000
```

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/` | API info | No |
| GET | `/api/health` | Health check | No |
| GET | `/api/ussd/catalog` | USSD bank codes | No |
| POST | `/api/contacts/sync` | Backup contacts (body: `{contacts:[...]}`) | Optional |
| GET | `/api/contacts` | Restore contacts | Optional |
| POST | `/api/log` | Log a call/USSD (body: `{number, type}`) | Optional |
| GET | `/api/log` | Get call history | Optional |

Set `X-Device-Id` header to separate data per device. If `AUTH_TOKEN` env var is set, also send `X-Auth-Token`.

## Notes

- No Docker. Pure Python + Gunicorn.
- SQLite by default (zero config). Add `DATABASE_URL` for PostgreSQL persistence.
- Free Render tier sleeps after 15 min idle — first request after sleep takes ~30 sec.
