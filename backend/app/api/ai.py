from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_retailer, require_role
from app.db import get_db
from app.models import Retailer, Role, User
from app.schemas import AiStatus, ExtractRequest, ExtractResponse
from app.services.ai.extraction import FALLBACK_PROVIDER, extract_text, get_extraction

router = APIRouter(prefix="/ai", tags=["ai"])

# The raw sample message supplied in the client brief (section 5.1).
SAMPLE_MESSAGE = "bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, chai patti 250 wala 1 peti"


@router.get("/status", response_model=AiStatus)
def status(_: User = Depends(require_role(Role.RETAILER))):
    s = get_settings()
    return {
        "provider": s.ai_provider if s.ai_configured else FALLBACK_PROVIDER,
        "model": s.ai_model if s.ai_configured else None,
        "configured": s.ai_configured,
        "sample_message": SAMPLE_MESSAGE,
    }


@router.post("/extract-text", response_model=ExtractResponse)
def extract(
    body: ExtractRequest,
    user: User = Depends(require_role(Role.RETAILER)),
    retailer: Retailer = Depends(get_current_retailer),
    db: Session = Depends(get_db),
):
    """Extract candidate lines from a message. This endpoint never creates an order."""
    return extract_text(db, user, retailer, body.message, body.language_hint)


@router.get("/extractions/{extraction_id}", response_model=ExtractResponse)
def extraction(extraction_id: int, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return get_extraction(db, retailer, extraction_id)
