# FMCG Retailer Ordering Platform with AI Order Capture

A responsive, installable web app for an FMCG distributor's kirana retailers and office order desk
(Isocode Labs take-home, Problem 5).

- **Retailers** sign in (demo OTP), browse a catalogue with their own dealer price, GST label, stock and
  schemes, build a cart, or paste a Hindi/Hinglish WhatsApp-style message and let AI propose order lines
  that they check and **explicitly confirm**.
- **The order desk** reviews a queue, sees credit and stock checks, corrects lines (with an audit trail),
  holds/approves/rejects orders, and exports approved orders to a Tally-friendly CSV without duplicates.

The backend is the source of truth for prices, schemes, GST, stock and credit. The LLM only proposes
structured candidate lines; it never prices, approves or places an order.

| | |
|---|---|
| Setup, deployment, env vars, demo logins | [deployment.md](deployment.md) |
| Technical design (architecture, assumptions, AI design, testing) | [docs/TDD.md](docs/TDD.md) |
| How to verify every requirement + client demo script | [docs/ACCEPTANCE_AND_DEMO.md](docs/ACCEPTANCE_AND_DEMO.md) |
| Browser end-to-end walkthrough (Playwright) | [e2e/walkthrough.cjs](e2e/walkthrough.cjs) |
| API docs (when running) | http://localhost:8000/docs |

## Quick start

```bash
# backend (needs PostgreSQL; see deployment.md for details)
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && cp .env.example .env   # set DATABASE_URL, JWT_SECRET_KEY
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload --port 8000
```

```bash
# frontend
cd frontend && npm install && npm run dev        # proxies /api to http://localhost:8000
```

Open http://localhost:5173. Demo accounts (synthetic): Retailer A `9000000001`, Retailer B `9000000002`,
Order desk `9000000009` — OTP `123456` (mock; no SMS is sent).

No AI key? The AI capture screen still works using a clearly-labelled rule-based fallback parser. Set
`AI_PROVIDER_API_KEY` (Groq by default) to use the LLM.

## Tests

```bash
cd backend
pytest -q                                                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/fmcg_test pytest -q   # + concurrency test
cd ../frontend && npm run build                                             # type-check + build
```

Covered: scheme engine boundaries and rounding, pricing/GST, stock (incl. free goods and concurrent
orders), credit holds, idempotent submission, authentication and role/ownership isolation, AI extraction
(sample message, unknown products, ambiguous units, malformed/timeout responses, invented SKUs, partial
extraction), human confirmation, desk workflow, optimistic locking, corrections and Tally export.

## Repository layout

```
backend/
  app/
    api/            FastAPI routers (auth, retailer, ai, desk) — thin; no business rules
    core/           settings, security (OTP/JWT), auth dependencies, money helpers, errors
    services/       scheme engine, catalogue, orders, desk workflow, export, aliases, audit
      ai/           LLM client, deterministic parsing, matching/confidence, extraction orchestration
    models.py       SQLAlchemy models        schemas.py  Pydantic request/response schemas
    seed.py         brief's sample catalogue + synthetic demo accounts/orders
  alembic/          migrations
  tests/            pytest suite
frontend/
  src/pages/        retailer (catalogue, cart, AI capture/review, orders) and desk screens
  src/api.ts        typed API client         src/state.tsx  auth, cart and data hooks
docs/TDD.md         technical design document
deployment.md       local setup, deployment, env var names, demo accounts, limitations
render.yaml         Render blueprint (API + PostgreSQL)    docker-compose.yml  local DB + API
```
