"""Items router (golden fixture: a well-formed generated router)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["items"])


class ItemOut(BaseModel):
    id: int
    name: str


def get_db() -> Session:
    raise NotImplementedError


@router.get("/{item_id}", response_model=ItemOut)
def read_item(item_id: int, db: Session = Depends(get_db)) -> ItemOut:
    """Return one item or 404."""
    try:
        item = db.get(object, item_id)
    except Exception as exc:
        logger.warning("read_item failed: %s", exc)
        raise HTTPException(status_code=500, detail="lookup failed") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return ItemOut(id=item_id, name="x")
