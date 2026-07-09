"""ERP/Procurement approval pattern: multi-level approval state machine.

Generated into src/approval_router.py of the target app.
Supports configurable approval tiers keyed by amount threshold.
"""

ERP_APPROVAL_REQUIREMENTS: list[str] = []  # No extra deps beyond base requirements

ERP_APPROVAL_CODE = '''\
"""ERP/Procurement approval router — multi-level approval state machine.

Approval flow (configurable via APPROVAL_THRESHOLDS env var):
  DRAFT → SUBMITTED → PENDING_L1 → [PENDING_L2 →] APPROVED | REJECTED | REVISION_NEEDED

Default thresholds (USD):
  < 1 000  → L1 only (manager)
  < 10 000 → L1 + L2 (director)
  ≥ 10 000 → L1 + L2 + L3 (CFO)
"""
from __future__ import annotations

import enum
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

try:
    from database import Base, get_db
    from routers.auth import get_current_user
except ImportError:
    from src.database import Base, get_db  # type: ignore[no-redef]
    from src.routers.auth import get_current_user  # type: ignore[no-redef]

router = APIRouter(prefix="/approvals", tags=["approvals"])

# ── Threshold configuration ────────────────────────────────────────────────────
# Each entry: (max_amount_exclusive, required_levels, label)
# Loaded once at startup; override via APPROVAL_THRESHOLDS env var (JSON).
_DEFAULT_THRESHOLDS = [
    (1_000.0,   1, "manager"),
    (10_000.0,  2, "director"),
    (float("inf"), 3, "cfo"),
]

def _get_thresholds() -> list[tuple[float, int, str]]:
    raw = os.environ.get("APPROVAL_THRESHOLDS", "")
    if not raw:
        return _DEFAULT_THRESHOLDS
    try:
        import json
        data = json.loads(raw)
        return [(float(t["max"]), int(t["levels"]), str(t["label"])) for t in data]
    except Exception as e:
        logger.warning("Failed to parse APPROVAL_THRESHOLDS env var, using defaults: %s", e)
        return _DEFAULT_THRESHOLDS

def required_levels(amount: float) -> int:
    for max_val, levels, _ in _get_thresholds():
        if amount < max_val:
            return levels
    return 3


# ── State machine ──────────────────────────────────────────────────────────────

class RequestStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_L1 = "pending_l1"
    PENDING_L2 = "pending_l2"
    PENDING_L3 = "pending_l3"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_NEEDED = "revision_needed"


class ApprovalAction(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_REVISION = "request_revision"


_LEVEL_TO_STATUS = {1: RequestStatus.PENDING_L1, 2: RequestStatus.PENDING_L2, 3: RequestStatus.PENDING_L3}
_STATUS_TO_LEVEL = {v: k for k, v in _LEVEL_TO_STATUS.items()}

def _next_status(current: RequestStatus, action: ApprovalAction, total_levels: int) -> RequestStatus:
    if action == ApprovalAction.REJECT:
        return RequestStatus.REJECTED
    if action == ApprovalAction.REQUEST_REVISION:
        return RequestStatus.REVISION_NEEDED
    # approve
    current_level = _STATUS_TO_LEVEL.get(current)
    if current_level is None:
        raise HTTPException(status_code=422, detail="Cannot approve from this state")
    if current_level >= total_levels:
        return RequestStatus.APPROVED
    return _LEVEL_TO_STATUS.get(current_level + 1, RequestStatus.APPROVED)


# ── SQLAlchemy Models ──────────────────────────────────────────────────────────

class PurchaseRequest(Base):
    __tablename__ = "erp_purchase_requests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_id = Column(String, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), default="USD")
    vendor = Column(String(255), default="")
    required_levels = Column(Integer, nullable=False, default=1)
    status = Column(SAEnum(RequestStatus), default=RequestStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ApprovalRecord(Base):
    __tablename__ = "erp_approval_records"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, ForeignKey("erp_purchase_requests.id"), nullable=False, index=True)
    approver_id = Column(String, nullable=False)
    level = Column(Integer, nullable=False)
    action = Column(SAEnum(ApprovalAction), nullable=False)
    comment = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Pydantic Schemas ───────────────────────────────────────────────────────────

class PurchaseRequestCreate(BaseModel):
    title: str
    description: str = ""
    amount: float
    currency: str = "USD"
    vendor: str = ""


class PurchaseRequestOut(BaseModel):
    id: str
    requester_id: str
    title: str
    description: str
    amount: float
    currency: str
    vendor: str
    required_levels: int
    status: RequestStatus
    created_at: datetime

    class Config:
        from_attributes = True


class ApprovalActionPayload(BaseModel):
    action: ApprovalAction
    comment: str = ""


class ApprovalRecordOut(BaseModel):
    id: str
    request_id: str
    approver_id: str
    level: int
    action: ApprovalAction
    comment: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/requests", response_model=PurchaseRequestOut, status_code=201)
async def create_request(
    payload: PurchaseRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> PurchaseRequestOut:
    levels = required_levels(payload.amount)
    req = PurchaseRequest(
        requester_id=str(current_user["id"]),
        required_levels=levels,
        **payload.model_dump(),
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req  # type: ignore[return-value]


@router.get("/requests", response_model=List[PurchaseRequestOut])
async def list_requests(
    skip: int = 0,
    limit: int = 50,
    status_filter: Optional[RequestStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[PurchaseRequestOut]:
    q = select(PurchaseRequest)
    # Non-admins only see their own requests
    if current_user.get("role") not in ("admin", "manager", "director", "cfo"):
        q = q.where(PurchaseRequest.requester_id == str(current_user["id"]))
    if status_filter:
        q = q.where(PurchaseRequest.status == status_filter)
    result = await db.execute(q.offset(skip).limit(min(limit, 100)))
    return result.scalars().all()  # type: ignore[return-value]


@router.get("/requests/{request_id}", response_model=PurchaseRequestOut)
async def get_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> PurchaseRequestOut:
    result = await db.execute(select(PurchaseRequest).where(PurchaseRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req  # type: ignore[return-value]


@router.post("/requests/{request_id}/submit", response_model=PurchaseRequestOut)
async def submit_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> PurchaseRequestOut:
    result = await db.execute(select(PurchaseRequest).where(PurchaseRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(req.requester_id) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Only the requester can submit")
    if req.status not in (RequestStatus.DRAFT, RequestStatus.REVISION_NEEDED):
        raise HTTPException(status_code=422, detail=f"Cannot submit from status: {req.status}")
    req.status = RequestStatus.PENDING_L1
    req.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)
    return req  # type: ignore[return-value]


@router.post("/requests/{request_id}/approve", response_model=PurchaseRequestOut)
async def act_on_request(
    request_id: str,
    payload: ApprovalActionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> PurchaseRequestOut:
    result = await db.execute(select(PurchaseRequest).where(PurchaseRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status not in (RequestStatus.PENDING_L1, RequestStatus.PENDING_L2, RequestStatus.PENDING_L3):
        raise HTTPException(status_code=422, detail=f"Request is not pending approval: {req.status}")
    current_level = _STATUS_TO_LEVEL.get(req.status, 1)
    new_status = _next_status(req.status, payload.action, req.required_levels)
    record = ApprovalRecord(
        request_id=request_id,
        approver_id=str(current_user["id"]),
        level=current_level,
        action=payload.action,
        comment=payload.comment,
    )
    db.add(record)
    req.status = new_status
    req.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)
    return req  # type: ignore[return-value]


@router.get("/requests/{request_id}/history", response_model=List[ApprovalRecordOut])
async def get_approval_history(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[ApprovalRecordOut]:
    result = await db.execute(
        select(ApprovalRecord)
        .where(ApprovalRecord.request_id == request_id)
        .order_by(ApprovalRecord.created_at)
    )
    return result.scalars().all()  # type: ignore[return-value]


@router.get("/queue", response_model=List[PurchaseRequestOut])
async def approval_queue(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[PurchaseRequestOut]:
    """Return all purchase requests currently awaiting any level of approval."""
    pending_statuses = [RequestStatus.PENDING_L1, RequestStatus.PENDING_L2, RequestStatus.PENDING_L3]
    result = await db.execute(
        select(PurchaseRequest).where(PurchaseRequest.status.in_(pending_statuses))
    )
    return result.scalars().all()  # type: ignore[return-value]
'''
