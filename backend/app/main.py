import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import ai, auth, desk, retailer
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.db import SessionLocal

logger = logging.getLogger("fmcg")

settings = get_settings()
settings.assert_safe_for_production()

app = FastAPI(
    title="FMCG Retailer Ordering API",
    version="1.0.0",
    description="Retailer catalogue, cart, AI order capture (human-confirmed) and order desk with Tally CSV export.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
)
app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Some fields are invalid.", "details": details}},
    )


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logger.exception("Unhandled error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500, content={"error": {"code": "server_error", "message": "Something went wrong. Please try again."}}
    )


@app.get("/health", tags=["meta"])
def health():
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ai_configured": settings.ai_configured,
            "demo_mode": settings.demo_mode}


app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(retailer.router)
app.include_router(ai.router)
app.include_router(desk.router)
