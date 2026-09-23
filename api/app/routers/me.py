"""Current-staff endpoint. Requires a valid token AND an existing staff account."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.app.auth.deps import get_current_staff
from api.app.models.public import Staff, StaffRole

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: int
    email: str
    role: StaffRole
    all_workspaces: bool


@router.get("/me", response_model=MeResponse)
def me(staff: Staff = Depends(get_current_staff)) -> Staff:
    return staff
