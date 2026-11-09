"""Append-only audit trail for order lifecycle, corrections, aliases and exports."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import AuditEvent


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def record(
    db: Session,
    *,
    actor_user_id: int | None,
    entity_type: str,
    entity_id: int,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    note: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_json=_jsonable(before) if before is not None else None,
        after_json=_jsonable(after) if after is not None else None,
        note=note,
    )
    db.add(event)
    return event
