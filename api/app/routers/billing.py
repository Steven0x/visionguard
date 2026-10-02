"""Billing routes (Slice 13): the Stripe webhook, staff-admin billing management, and the agency
billing-contact portal surface.

- ``webhook_router``  — ``POST /billing/webhook``: UNAUTHENTICATED but Stripe-signature-gated.
  Explicitly allowlisted in the default-deny route walk (it has no staff/agency identity).
- ``admin_router``    — ``/workspaces/{id}/billing/*``: ``require_role(admin)`` (agency → 403).
- ``portal_router``   — ``/portal/billing*``: agency, and the write actions require the caller to be
  the designated billing contact.

Quantity is NEVER accepted from a client — it is derived server-side from the active-subject count.
See docs/specs/billing.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.app.auth.deps import (
    AgencyContext,
    get_agency_context,
    require_role,
    require_workspace_access,
)
from api.app.billing.client import SignatureError
from api.app.config import get_settings
from api.app.models.billing import BillingCadence, BillingMode, PlanTier
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import billing as svc

# ── Webhook (unauthenticated, signature-gated) ──────────────────────────────────
webhook_router = APIRouter(prefix="/billing", tags=["billing-webhook"])


@webhook_router.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        result = svc.process_webhook(payload, signature)
    except SignatureError as exc:
        # A forged/replayed-with-bad-sig event never changes state.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="bad signature"
        ) from exc
    return {"result": result}


# ── Staff admin ─────────────────────────────────────────────────────────────────
admin_router = APIRouter(prefix="/workspaces/{workspace_id}/billing", tags=["billing-admin"])
_ADMIN = require_role(StaffRole.admin)


def _app_base() -> str:
    origins = get_settings().allowed_origin_list
    return origins[0] if origins else "http://localhost:5173"


def _return_urls() -> tuple[str, str]:
    base = _app_base()
    return f"{base}/billing/success", f"{base}/billing/cancel"


class ModeIn(BaseModel):
    mode: BillingMode


class CheckoutIn(BaseModel):
    plan_tier: PlanTier
    cadence: BillingCadence


class OverrideIn(BaseModel):
    priority_override: bool | None = None
    discovery_frequency_override: str | None = None


class ContactIn(BaseModel):
    staff_id: int


class UrlOut(BaseModel):
    url: str


@admin_router.get("")
def get_billing(
    workspace: Workspace = Depends(require_workspace_access),
    _staff: Staff = Depends(_ADMIN),
) -> dict:
    return svc.get_status(workspace.id)


@admin_router.put("/mode")
def set_mode(
    payload: ModeIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> dict:
    svc.set_mode(workspace.id, actor_staff_id=staff.id, mode=payload.mode)
    return svc.get_status(workspace.id)


@admin_router.post("/checkout", response_model=UrlOut)
def create_checkout(
    payload: CheckoutIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> UrlOut:
    success_url, cancel_url = _return_urls()
    url = svc.create_checkout(
        workspace.id,
        actor_staff_id=staff.id,
        plan_tier=payload.plan_tier,
        cadence=payload.cadence,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return UrlOut(url=url)


@admin_router.post("/onboarding-checkout", response_model=UrlOut)
def create_onboarding_checkout(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> UrlOut:
    success_url, cancel_url = _return_urls()
    url = svc.create_onboarding_checkout(
        workspace.id, actor_staff_id=staff.id, success_url=success_url, cancel_url=cancel_url
    )
    return UrlOut(url=url)


@admin_router.post("/portal", response_model=UrlOut)
def create_portal(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> UrlOut:
    url = svc.create_portal(workspace.id, actor_staff_id=staff.id, return_url=_app_base())
    return UrlOut(url=url)


@admin_router.post("/onboarding-credit")
def apply_onboarding_credit(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> dict:
    svc.apply_onboarding_credit(workspace.id, actor_staff_id=staff.id)
    return svc.get_status(workspace.id)


@admin_router.post("/coupon")
def apply_coupon(
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> dict:
    svc.apply_design_partner_coupon(workspace.id, actor_staff_id=staff.id)
    return svc.get_status(workspace.id)


@admin_router.post("/override")
def set_override(
    payload: OverrideIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> dict:
    svc.set_override(
        workspace.id,
        actor_staff_id=staff.id,
        priority_override=payload.priority_override,
        discovery_frequency_override=payload.discovery_frequency_override,
    )
    return svc.get_status(workspace.id)


@admin_router.put("/billing-contact")
def set_billing_contact(
    payload: ContactIn,
    workspace: Workspace = Depends(require_workspace_access),
    staff: Staff = Depends(_ADMIN),
) -> dict:
    svc.set_billing_contact(workspace.id, actor_staff_id=staff.id, staff_id=payload.staff_id)
    return svc.get_status(workspace.id)


# ── Agency portal (billing contact) ──────────────────────────────────────────────
portal_router = APIRouter(prefix="/portal/billing", tags=["billing-portal"])


def _require_contact(ctx: AgencyContext) -> dict:
    """Return the portal status, or 403 if the caller isn't the designated billing contact."""
    view = svc.get_portal_status(ctx.workspace.id, ctx.staff.id)
    if not view["is_billing_contact"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the designated billing contact can manage billing",
        )
    return view


@portal_router.get("")
def portal_status(ctx: AgencyContext = Depends(get_agency_context)) -> dict:
    return svc.get_portal_status(ctx.workspace.id, ctx.staff.id)


@portal_router.post("/checkout", response_model=UrlOut)
def portal_checkout(
    payload: CheckoutIn, ctx: AgencyContext = Depends(get_agency_context)
) -> UrlOut:
    _require_contact(ctx)
    success_url, cancel_url = _return_urls()
    url = svc.create_checkout(
        ctx.workspace.id,
        actor_staff_id=ctx.staff.id,
        plan_tier=payload.plan_tier,
        cadence=payload.cadence,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return UrlOut(url=url)


@portal_router.post("/portal", response_model=UrlOut)
def portal_manage(ctx: AgencyContext = Depends(get_agency_context)) -> UrlOut:
    _require_contact(ctx)
    url = svc.create_portal(ctx.workspace.id, actor_staff_id=ctx.staff.id, return_url=_app_base())
    return UrlOut(url=url)
