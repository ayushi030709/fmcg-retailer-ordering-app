"""FastAPI dependencies for authentication and role-based authorization.

Authorization is enforced here and in the service layer — hiding a button in
React is not authorization.
"""

from collections.abc import Callable

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db import get_db
from app.models import Retailer, Role, User


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "not_authenticated", "Sign in to continue.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AppError(401, "invalid_token", "Your session has expired. Please sign in again.")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "invalid_token", "Your session has expired. Please sign in again.")
    return user


def require_role(*roles: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have access to this area.")
        return user

    return checker


def get_current_retailer(
    user: User = Depends(require_role(Role.RETAILER)), db: Session = Depends(get_db)
) -> Retailer:
    retailer = db.query(Retailer).filter(Retailer.user_id == user.id, Retailer.is_active.is_(True)).one_or_none()
    if retailer is None:
        raise AppError(403, "forbidden", "No active retailer account is linked to this user.")
    return retailer


require_desk = require_role(Role.ORDER_DESK)
