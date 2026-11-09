import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.errors import AppError
from app.core.security import create_access_token, generate_otp, hash_otp, verify_otp
from app.db import get_db
from app.models import OtpChallenge, Retailer, Role, User
from app.schemas import CreditSummary, Me, OtpRequest, OtpRequestResponse, OtpVerify, RetailerProfile, TokenResponse
from app.services.orders import credit_check

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])

GENERIC_SENT = "If this number or email is registered, a one-time code has been sent."


def _normalise_identifier(raw: str) -> str:
    raw = raw.strip()
    if "@" in raw:
        return raw.lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


@router.post("/request-otp", response_model=OtpRequestResponse)
def request_otp(body: OtpRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    ident = _normalise_identifier(body.identifier)
    user = db.scalar(select(User).where(or_(User.phone == ident, User.email == ident), User.is_active.is_(True)))
    challenge_id = str(uuid.uuid4())
    hint = (
        f"Demo mode: no SMS is sent. Use the reviewer code {settings.demo_otp}." if settings.demo_mode else None
    )
    if user is None:
        # Same response shape for unknown users, so accounts cannot be enumerated.
        return OtpRequestResponse(
            challenge_id=challenge_id, expires_in=settings.otp_ttl_seconds, message=GENERIC_SENT,
            demo_mode=settings.demo_mode, demo_hint=hint,
        )
    now = datetime.now(timezone.utc)
    # Invalidate older unused challenges for this user.
    db.execute(
        update(OtpChallenge)
        .where(OtpChallenge.user_id == user.id, OtpChallenge.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    salt = secrets.token_hex(16)
    otp = generate_otp()
    db.add(
        OtpChallenge(
            id=challenge_id,
            user_id=user.id,
            otp_hash=hash_otp(otp, salt),
            salt=salt,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )
    db.commit()
    return OtpRequestResponse(
        challenge_id=challenge_id, expires_in=settings.otp_ttl_seconds, message=GENERIC_SENT,
        demo_mode=settings.demo_mode, demo_hint=hint,
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify(body: OtpVerify, db: Session = Depends(get_db)):
    settings = get_settings()
    challenge = db.get(OtpChallenge, body.challenge_id, with_for_update=True)
    invalid = AppError(401, "invalid_otp", "That code is not correct. Check it and try again.")
    if challenge is None or challenge.consumed_at is not None:
        raise AppError(401, "otp_expired", "This code has expired or was already used. Request a new code.")
    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:  # SQLite returns naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AppError(401, "otp_expired", "This code has expired. Request a new code.")
    if challenge.attempts >= settings.otp_max_attempts:
        raise AppError(429, "otp_locked", "Too many wrong attempts. Request a new code.")
    if not verify_otp(body.otp, challenge.salt, challenge.otp_hash):
        challenge.attempts += 1
        db.commit()
        raise invalid
    challenge.consumed_at = datetime.now(timezone.utc)
    user = db.get(User, challenge.user_id)
    if user is None or not user.is_active:
        raise invalid
    db.commit()
    token, expires_in = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, user=build_me(db, user))


def build_me(db: Session, user: User) -> Me:
    profile, credit = None, None
    if user.role == Role.RETAILER:
        retailer = db.scalar(select(Retailer).where(Retailer.user_id == user.id))
        if retailer is not None:
            profile = RetailerProfile.model_validate(retailer)
            credit = CreditSummary(**credit_check(db, retailer, Decimal("0")))
    return Me(
        id=user.id, name=user.name, role=user.role, phone=user.phone, email=user.email, retailer=profile, credit=credit
    )


@me_router.get("/me", response_model=Me)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_me(db, user)
