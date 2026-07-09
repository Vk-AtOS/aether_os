"""Marketplace pattern: listing/bidding endpoints + escrow state machine.

Generated into src/marketplace_router.py of the target app.
"""

MARKETPLACE_REQUIREMENTS: list[str] = []  # No extra deps beyond base requirements

MARKETPLACE_CODE = '''\
"""Marketplace router — listings, bids, and escrow state machine.

Escrow states: PENDING → FUNDED → RELEASED | DISPUTED → RESOLVED
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

try:
    from database import Base, get_db
    from routers.auth import get_current_user
except ImportError:
    from src.database import Base, get_db  # type: ignore[no-redef]
    from src.routers.auth import get_current_user  # type: ignore[no-redef]

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── State machine ──────────────────────────────────────────────────────────────

class ListingStatus(str, enum.Enum):
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"


class BidStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class EscrowState(str, enum.Enum):
    PENDING = "pending"
    FUNDED = "funded"
    RELEASED = "released"
    DISPUTED = "disputed"
    RESOLVED = "resolved"

_ESCROW_TRANSITIONS: dict[EscrowState, list[EscrowState]] = {
    EscrowState.PENDING: [EscrowState.FUNDED],
    EscrowState.FUNDED: [EscrowState.RELEASED, EscrowState.DISPUTED],
    EscrowState.DISPUTED: [EscrowState.RESOLVED],
    EscrowState.RELEASED: [],
    EscrowState.RESOLVED: [],
}

def _transition_escrow(current: EscrowState, target: EscrowState) -> EscrowState:
    if target not in _ESCROW_TRANSITIONS.get(current, []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid escrow transition: {current} → {target}",
        )
    return target


# ── SQLAlchemy Models ──────────────────────────────────────────────────────────

class Listing(Base):
    __tablename__ = "marketplace_listings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    seller_id = Column(String, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    price = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(ListingStatus), default=ListingStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Bid(Base):
    __tablename__ = "marketplace_bids"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id = Column(String, ForeignKey("marketplace_listings.id"), nullable=False, index=True)
    bidder_id = Column(String, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    message = Column(Text, default="")
    status = Column(Enum(BidStatus), default=BidStatus.PENDING)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Escrow(Base):
    __tablename__ = "marketplace_escrows"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    bid_id = Column(String, ForeignKey("marketplace_bids.id"), nullable=False, unique=True)
    buyer_id = Column(String, nullable=False)
    seller_id = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    state = Column(Enum(EscrowState), default=EscrowState.PENDING)
    dispute_reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Pydantic Schemas ───────────────────────────────────────────────────────────

class ListingCreate(BaseModel):
    title: str
    description: str = ""
    price: float


class ListingOut(BaseModel):
    id: str
    seller_id: str
    title: str
    description: str
    price: float
    status: ListingStatus
    created_at: datetime

    class Config:
        from_attributes = True


class BidCreate(BaseModel):
    amount: float
    message: str = ""


class BidOut(BaseModel):
    id: str
    listing_id: str
    bidder_id: str
    amount: float
    message: str
    status: BidStatus
    created_at: datetime

    class Config:
        from_attributes = True


class EscrowOut(BaseModel):
    id: str
    bid_id: str
    buyer_id: str
    seller_id: str
    amount: float
    state: EscrowState
    created_at: datetime

    class Config:
        from_attributes = True


# ── Listing Endpoints ──────────────────────────────────────────────────────────

@router.post("/listings", response_model=ListingOut, status_code=201)
async def create_listing(
    payload: ListingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ListingOut:
    listing = Listing(seller_id=str(current_user["id"]), **payload.model_dump())
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return listing  # type: ignore[return-value]


@router.get("/listings", response_model=List[ListingOut])
async def list_listings(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[ListingOut]:
    result = await db.execute(
        select(Listing)
        .where(Listing.status == ListingStatus.ACTIVE)
        .offset(skip)
        .limit(min(limit, 100))
    )
    return result.scalars().all()  # type: ignore[return-value]


@router.get("/listings/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ListingOut:
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing  # type: ignore[return-value]


@router.delete("/listings/{listing_id}", status_code=204)
async def cancel_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if str(listing.seller_id) != str(current_user["id"]) and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not the seller")
    listing.status = ListingStatus.CANCELLED
    await db.commit()


# ── Bid Endpoints ──────────────────────────────────────────────────────────────

@router.post("/listings/{listing_id}/bids", response_model=BidOut, status_code=201)
async def place_bid(
    listing_id: str,
    payload: BidCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> BidOut:
    listing_result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = listing_result.scalar_one_or_none()
    if not listing or listing.status != ListingStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Listing not found or not active")
    if str(listing.seller_id) == str(current_user["id"]):
        raise HTTPException(status_code=400, detail="Cannot bid on your own listing")
    bid = Bid(listing_id=listing_id, bidder_id=str(current_user["id"]), **payload.model_dump())
    db.add(bid)
    await db.commit()
    await db.refresh(bid)
    return bid  # type: ignore[return-value]


@router.get("/listings/{listing_id}/bids", response_model=List[BidOut])
async def get_bids(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> List[BidOut]:
    result = await db.execute(select(Bid).where(Bid.listing_id == listing_id))
    return result.scalars().all()  # type: ignore[return-value]


@router.put("/listings/{listing_id}/bids/{bid_id}/accept", response_model=EscrowOut)
async def accept_bid(
    listing_id: str,
    bid_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    listing_result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = listing_result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if str(listing.seller_id) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Only the seller can accept bids")
    bid_result = await db.execute(select(Bid).where(Bid.id == bid_id, Bid.listing_id == listing_id))
    bid = bid_result.scalar_one_or_none()
    if not bid or bid.status != BidStatus.PENDING:
        raise HTTPException(status_code=404, detail="Bid not found or not pending")
    bid.status = BidStatus.ACCEPTED
    listing.status = ListingStatus.SOLD
    escrow = Escrow(
        bid_id=bid_id,
        buyer_id=str(bid.bidder_id),
        seller_id=str(listing.seller_id),
        amount=bid.amount,
    )
    db.add(escrow)
    await db.commit()
    await db.refresh(escrow)
    return escrow  # type: ignore[return-value]


@router.put("/listings/{listing_id}/bids/{bid_id}/reject", status_code=204)
async def reject_bid(
    listing_id: str,
    bid_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    bid_result = await db.execute(select(Bid).where(Bid.id == bid_id, Bid.listing_id == listing_id))
    bid = bid_result.scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    bid.status = BidStatus.REJECTED
    await db.commit()


# ── Escrow Endpoints ───────────────────────────────────────────────────────────

@router.get("/escrow/{escrow_id}", response_model=EscrowOut)
async def get_escrow(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    result = await db.execute(select(Escrow).where(Escrow.id == escrow_id))
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    uid = str(current_user["id"])
    if uid not in (str(escrow.buyer_id), str(escrow.seller_id)) and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return escrow  # type: ignore[return-value]


@router.post("/escrow/{escrow_id}/fund", response_model=EscrowOut)
async def fund_escrow(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    result = await db.execute(select(Escrow).where(Escrow.id == escrow_id))
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if str(escrow.buyer_id) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Only the buyer can fund escrow")
    escrow.state = _transition_escrow(escrow.state, EscrowState.FUNDED)
    escrow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(escrow)
    return escrow  # type: ignore[return-value]


@router.post("/escrow/{escrow_id}/release", response_model=EscrowOut)
async def release_escrow(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    result = await db.execute(select(Escrow).where(Escrow.id == escrow_id))
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if str(escrow.buyer_id) != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Only the buyer can release escrow")
    escrow.state = _transition_escrow(escrow.state, EscrowState.RELEASED)
    escrow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(escrow)
    return escrow  # type: ignore[return-value]


@router.post("/escrow/{escrow_id}/dispute", response_model=EscrowOut)
async def dispute_escrow(
    escrow_id: str,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    result = await db.execute(select(Escrow).where(Escrow.id == escrow_id))
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    uid = str(current_user["id"])
    if uid not in (str(escrow.buyer_id), str(escrow.seller_id)):
        raise HTTPException(status_code=403, detail="Only buyer or seller can dispute")
    escrow.state = _transition_escrow(escrow.state, EscrowState.DISPUTED)
    escrow.dispute_reason = reason
    escrow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(escrow)
    return escrow  # type: ignore[return-value]


@router.post("/escrow/{escrow_id}/resolve", response_model=EscrowOut)
async def resolve_escrow(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> EscrowOut:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can resolve disputes")
    result = await db.execute(select(Escrow).where(Escrow.id == escrow_id))
    escrow = result.scalar_one_or_none()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    escrow.state = _transition_escrow(escrow.state, EscrowState.RESOLVED)
    escrow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(escrow)
    return escrow  # type: ignore[return-value]
'''
