# Deployment Guide — FMCG Retailer Ordering Platform

Source code: https://github.com/NGACA-Ggn/create

## Prerequisites

| Tool | Version used | Minimum |
|---|---|---|
| Python | 3.13 (local), 3.12 (Docker image) | 3.11 |
| Node.js | 22 | 20 |
| npm | 10 | 9 |
| PostgreSQL | 16 | 14 |

SQLite is used only by the automated tests (zero setup); the app itself runs on PostgreSQL.

## Local setup

1. **Clone the public GitHub repository**
   ```bash
   git clone https://github.com/NGACA-Ggn/create.git fmcg-ordering && cd fmcg-ordering
   ```
2. **Create and activate a Python virtual environment**
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```
3. **Install backend requirements**
   ```bash
   pip install -r requirements-dev.txt
   ```
4. **Copy `backend/.env.example` to `backend/.env` and fill local values**
   ```bash
   cp .env.example .env
   ```
   Set `JWT_SECRET_KEY` to any long random string. Leave `AI_PROVIDER_API_KEY` empty to use the
   clearly-labelled rule-based fallback parser, or set a Groq API key to use the LLM path.
5. **Create the PostgreSQL database and run migrations**
   ```bash
   createdb fmcg_dev                 # or: docker compose up -d db   (see "Docker option" below)
   alembic upgrade head
   ```
   `DATABASE_URL` in `.env` must point at this database, e.g.
   `postgresql+psycopg://<user>:<password>@localhost:5432/fmcg_dev`.
6. **Seed the sample data**
   ```bash
   python -m app.seed                # seeds only if the database is empty
   python -m app.seed --reset        # wipe all rows and re-seed (demo/dev only)
   ```
7. **Start the FastAPI server**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Interactive API docs: http://localhost:8000/docs · health check: http://localhost:8000/health
8. **Install frontend dependencies** (new terminal)
   ```bash
   cd frontend
   npm install
   ```
9. **Configure the frontend API base URL**
   Nothing to do locally: the app calls `/api/...` and the Vite dev server proxies it to
   `http://127.0.0.1:8000` (set `API_PROXY_TARGET` to proxy elsewhere, e.g. if port 8000 is taken). For a deployed frontend, set
   `VITE_API_BASE_URL` to the public API URL (see "Frontend on Vercel").
10. **Start the frontend development server**
    ```bash
    npm run dev
    ```
    Open http://localhost:5173 and sign in with a demo account below.

### Quick local demo without PostgreSQL or Docker (SQLite, Windows-friendly)

For a quick look on a laptop, the API also runs on a local SQLite file. PostgreSQL remains the
supported database (SQLite has no row locks, so the concurrent-order protection only applies on PostgreSQL).
Windows PowerShell (one command per line; no `&&` and no venv activation needed):

```bash
cd backend
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Content .env "DATABASE_URL=sqlite:///./fmcg_local.db`nJWT_SECRET_KEY=local-dev-only-change-me`nFRONTEND_ORIGIN=http://localhost:5173"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m app.seed
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
On macOS/Linux use `python3 -m venv .venv`, `.venv/bin/python …`, and put the same three lines in `backend/.env`.
Then start the frontend (steps 8–10) in a second terminal.

### Docker option (database + API)

```bash
docker compose up --build
```
This starts PostgreSQL 16 and the API on http://localhost:8000 (migrations and seed run automatically
on start). Then run the frontend with steps 8–10.

### Running the tests

```bash
cd backend
pytest -q                                                    # SQLite, no setup needed
TEST_DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/fmcg_test pytest -q
```
The PostgreSQL run additionally executes the concurrent-order (no oversell) test, which needs real row locks.
Point `TEST_DATABASE_URL` at a **separate, disposable** database — the tests drop and recreate all tables.

Frontend type-check and production build: `cd frontend && npm run build`.

GitHub Actions (`.github/workflows/ci.yml`) runs the backend tests on SQLite and PostgreSQL, checks the
migration, and builds the frontend on every push and pull request.

## Deployment

| | |
|---|---|
| Frontend URL | **[TO FILL after deploying]** |
| Backend URL | **[TO FILL after deploying]** |
| Database hosting | Render PostgreSQL (created by `render.yaml`) — or any managed PostgreSQL such as Neon |

The recommended setup is **Render** for the API + PostgreSQL and **Vercel** for the static frontend.
Free tiers change often — verify current limits (sleep on idle, database expiry, build minutes) before
relying on them for the review period.

### Backend + database on Render

1. Push this repository to GitHub (it must stay public until the review is complete).
2. In Render choose **New → Blueprint**, select the repository. `render.yaml` creates:
   - `fmcg-ordering-db` — a PostgreSQL database;
   - `fmcg-ordering-api` — a Docker web service built from `backend/Dockerfile`, with `DATABASE_URL`
     wired to the database and `JWT_SECRET_KEY` generated by Render.
3. When prompted, enter the values marked `sync: false`: `FRONTEND_ORIGIN` (the Vercel URL from the next
   section — you can fill it in after the frontend is deployed) and optionally `AI_PROVIDER_API_KEY`.
4. Deploy. On every start the container runs `alembic upgrade head`, then `python -m app.seed`
   (seeds only an empty database), then starts Uvicorn. Check `https://<api-host>/health`.

### Frontend on Vercel

1. **New Project** → import the repository → set **Root Directory** to `frontend` (framework preset: Vite).
2. Environment variable: `VITE_API_BASE_URL=https://<api-host>` (no trailing slash).
3. Deploy. `frontend/vercel.json` rewrites all routes to `index.html` (client-side routing) and sets
   long-lived caching for hashed assets.
4. Copy the Vercel URL into the API's `FRONTEND_ORIGIN` on Render (comma-separate several origins if
   needed) and redeploy the API so CORS allows it.

### Migration and seed procedure

| Situation | Command (run in `backend/` with `DATABASE_URL` set) |
|---|---|
| New database / new release | `alembic upgrade head` (automatic in the Docker start command) |
| First deploy | `python -m app.seed` (automatic; no-op when data exists) |
| Reset the demo to a clean state | `python -m app.seed --reset` (Render: service → Shell) — **deletes all data** |
| New schema change (development) | edit `app/models.py`, then `alembic revision --autogenerate -m "..."` and review the file |

## Environment variable names

Values are never committed. See `backend/.env.example` and `frontend/.env.example` for safe placeholders.

**Backend**

| Name | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (`postgres://` and `postgresql://` are normalised to the psycopg driver) |
| `JWT_SECRET_KEY` | Signs session tokens and keys the OTP HMAC. Must be long and random; the app refuses to start in production with the dev default |
| `JWT_EXPIRES_MINUTES` | Session length (default 720) |
| `APP_ENV` | `development` \| `test` \| `production` |
| `FRONTEND_ORIGIN` | Comma-separated browser origins allowed by CORS |
| `DEMO_MODE` | `true` = fixed reviewer OTP, no SMS is sent |
| `DEMO_OTP` | The reviewer OTP used in demo mode |
| `AI_PROVIDER` | `groq` (default). Any OpenAI-compatible chat-completions provider works with `AI_BASE_URL` |
| `AI_PROVIDER_API_KEY` | Server-side LLM key. Empty = rule-based fallback parser (clearly labelled in the UI) |
| `AI_MODEL` | LLM model name (default `llama-3.3-70b-versatile`) |
| `AI_BASE_URL` | Provider base URL (default `https://api.groq.com/openai/v1`) |
| `AI_TIMEOUT_SECONDS` | LLM request timeout (default 20) |

**Frontend**

| Name | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Public URL of the FastAPI backend (production builds). Unset locally → `/api` via the Vite proxy |
| `API_PROXY_TARGET` | Dev/preview only: where the Vite `/api` proxy forwards (default `http://127.0.0.1:8000`) |

## Reviewer demo accounts

All accounts, shops, phone numbers, credit figures and historical orders are **synthetic demo data**.
Sign-in uses a **mock OTP**: no SMS is sent. After requesting a code, enter the demo OTP **`123456`**
(the value of `DEMO_OTP`; the sign-in screen also shows it in demo mode). The sign-in page has one-tap
buttons for each account.

| Role | Sign in with | What to try |
|---|---|---|
| Retailer A — "Demo Kirana Store A" | `9000000001` | Catalogue → cart → order. AI capture with the sample message: "peti" is asked about (no saved vocabulary); confirm and tick "remember" — the next extraction understands it. |
| Retailer B — "Demo General Store B" | `9000000002` | Low available credit: most orders go **on hold** for credit review. Has a saved "peti = case" alias, a saved phrase for biscuits and a synthetic negotiated detergent price (₹99.00 instead of ₹101.50) that only B can see. |
| Order desk — "Demo Order Desk" | `9000000009` or `desk@demo.local` | Queue with pending, on-hold, approved and exported examples; approve/hold/release/reject; correct a line; export approved orders to CSV; review saved retailer phrases. |

The AI capture screen has a **Use sample message** button that inserts the raw message from the brief:
`bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, chai patti 250 wala 1 peti`.

## Known limitations

- **OTP is mocked** (assumption A2). No SMS provider is integrated; `DEMO_MODE=false` would generate
  random codes that nobody receives.
- **LLM path needs a key.** Without `AI_PROVIDER_API_KEY` the app uses a rule-based fallback parser,
  labelled as such in the UI and API. The Groq request/response handling is covered by tests with mocked
  provider responses; it was not exercised against the live provider in the development environment.
- **GST rate (18%) and the GST-exclusive pricing policy are demo assumptions** (A1); dealer prices are
  treated as per-case, following the brief's worked example — to be confirmed with the client.
- **Tally CSV** uses documented, stable columns; the final import mapping must be confirmed against the
  client's Tally configuration (A7).
- Not built (optional scope): image/OCR and voice capture, salesman/offline mode, service-worker offline
  caching, messaging integrations, payments and delivery tracking, admin screens for products, stock,
  schemes and credit limits.
- Outstanding balances are seeded values; there is no sync back from Tally.
- On free hosting tiers the API may sleep when idle, so the first request after a pause can take tens of
  seconds.
