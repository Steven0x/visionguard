"""Current-staff endpoint. Requires a valid token AND an existing staff account."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from api.app.auth.deps import get_current_staff
from api.app.db.session import public_session
from api.app.models.public import Staff, StaffRole

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: int
    email: str
    role: StaffRole
    all_workspaces: bool
    review_keep_blur: bool


class ReviewPrefsIn(BaseModel):
    keep_blur: bool


class ReviewPrefsOut(BaseModel):
    review_keep_blur: bool


@router.get("/me", response_model=MeResponse)
def me(staff: Staff = Depends(get_current_staff)) -> Staff:
    return staff


@router.put("/me/review-prefs", response_model=ReviewPrefsOut)
def update_review_prefs(
    payload: ReviewPrefsIn, staff: Staff = Depends(get_current_staff)
) -> ReviewPrefsOut:
    with public_session() as session:
        row = session.scalar(select(Staff).where(Staff.id == staff.id))
        if row is not None:  # public_session commits on context exit
            row.review_keep_blur = payload.keep_blur
    return ReviewPrefsOut(review_keep_blur=payload.keep_blur)
