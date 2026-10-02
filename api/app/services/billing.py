"""Billing service (Slice 13) — the one place billing logic lives.

Stripe is the source of truth; ``workspace_billing`` is a thin mirror. This module:
  * derives the subscription quantity from the active-subject count (never from a client),
  * keeps the mirror in sync (webhooks re-fetch from Stripe; a daily beat reconciles),
  * enforces the two suspension gates (new subjects, new discovery) — and NOTHING else,
  * runs the staff-admin actions (checkout/portal/credit/coupon/override/contact/mode).

Mirror rows live in the public schema; billing AUDIT rows land in the tenant ``audit_log``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.billing import get_billing_client
from api.app.billing.client import SubscriptionView
from api.app.config import Settings, get_settings
from api.app.db.base import schema_for_workspace
from api.app.db.session import public_session, tenant_session
from api.app.models.billing import (
    BillingCadence,
    BillingMode,
    BillingStatus,
    PlanTier,
    WorkspaceBilling,
)
from api.app.models.public import Staff, StaffRole, StaffWorkspaceAccess, Workspace
from api.app.models.subjects import Subject, SubjectStatus

logger = logging.getLogger("visionguard.billing")

_FREQ_RANK = {"off": 0, "weekly": 1, "daily": 2}
_ACTIVE_SUB_STATUSES = {BillingStatus.active, BillingStatus.trialing, BillingStatus.past_due}


class BillingError(Exception):
    """A billing precondition failed (→ 409)."""


class BillingSuspended(Exception):
    """A new-work action is blocked because the workspace is suspended for non-payment (→ 402)."""


@dataclass(frozen=True)
class SyncResult:
    changed: bool
    observed: int
    desired: int


# ── get-or-create ────────────────────────────────────────────────────────────
def get_or_create(session: Session, workspace_id: int) -> WorkspaceBilling:
    """The workspace's billing row, created at manual mode if missing (gates skip manual)."""
    billing = session.get(WorkspaceBilling, workspace_id)
    if billing is None:
        billing = WorkspaceBilling(workspace_id=workspace_id, billing_mode=BillingMode.manual)
        session.add(billing)
        session.flush()
    return billing


# ── pure helpers ──────────────────────────────────────────────────────────────
def _price_map(settings: Settings) -> dict[str, tuple[PlanTier, BillingCadence]]:
    raw = {
        settings.stripe_price_core_monthly: (PlanTier.core, BillingCadence.monthly),
        settings.stripe_price_core_annual: (PlanTier.core, BillingCadence.annual),
        settings.stripe_price_priority_monthly: (PlanTier.priority, BillingCadence.monthly),
        settings.stripe_price_priority_annual: (PlanTier.priority, BillingCadence.annual),
    }
    return {pid: v for pid, v in raw.items() if pid}


def _price_for(settings: Settings, tier: PlanTier, cadence: BillingCadence) -> str:
    for pid, (t, c) in _price_map(settings).items():
        if t == tier and c == cadence:
            return pid
    raise BillingError(f"no Stripe price configured for {tier}/{cadence}")


def desired_quantity(active_count: int, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return max(active_count, settings.billing_min_quantity)


def effective_priority(billing: WorkspaceBilling) -> bool:
    if billing.priority_override is not None:
        return billing.priority_override
    return billing.plan_tier == PlanTier.priority


def effective_max_frequency(billing: WorkspaceBilling) -> str:
    """The fastest ScanFrequency this workspace may run. Manual mode is uncapped ('daily')."""
    if billing.billing_mode != BillingMode.stripe:
        return "daily"
    if billing.discovery_frequency_override:
        return billing.discovery_frequency_override
    return "daily" if effective_priority(billing) else "weekly"


def cap_frequency(configured: str, allowed: str) -> str:
    """Clamp a configured ScanFrequency to the plan-allowed maximum speed."""
    if _FREQ_RANK.get(configured, 0) <= _FREQ_RANK.get(allowed, 2):
        return configured
    return allowed


def is_in_grace(billing: WorkspaceBilling, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return (
        billing.billing_mode == BillingMode.stripe
        and billing.status == BillingStatus.past_due
        and billing.grace_until is not None
        and now <= billing.grace_until
    )


def is_suspended(billing: WorkspaceBilling, now: datetime | None = None) -> bool:
    """Suspended = stripe mode AND (never-subscribed | canceled | past_due past grace).

    Manual mode and active/trialing are never suspended. A past_due row inside its grace window is
    NOT suspended (banner only). Fails OPEN (not suspended) if a past_due row somehow lacks a grace
    deadline — never stopping work is the stronger rule than collecting on time.
    """
    if billing.billing_mode != BillingMode.stripe:
        return False
    now = now or datetime.now(UTC)
    if billing.status in (BillingStatus.active, BillingStatus.trialing):
        return False
    if billing.status in (BillingStatus.none, BillingStatus.canceled):
        return True
    if billing.status == BillingStatus.past_due:
        return billing.grace_until is not None and now > billing.grace_until
    return False


def get_status(workspace_id: int) -> dict:
    """Staff-facing billing status for a workspace (creates a manual row if none exists)."""
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        view = status_view(billing)
        view["billing_contact_staff_id"] = billing.billing_contact_staff_id
        view["has_customer"] = billing.stripe_customer_id is not None
        return view


def get_portal_status(workspace_id: int, caller_staff_id: int) -> dict:
    """Portal billing status: adds whether the caller is the billing contact + the contact email."""
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        view = status_view(billing)
        contact_email = None
        if billing.billing_contact_staff_id is not None:
            contact = session.get(Staff, billing.billing_contact_staff_id)
            contact_email = contact.email if contact else None
        view["is_billing_contact"] = billing.billing_contact_staff_id == caller_staff_id
        view["billing_contact_email"] = contact_email
        return view


def status_view(billing: WorkspaceBilling, now: datetime | None = None) -> dict:
    return {
        "billing_mode": str(billing.billing_mode),
        "status": str(billing.status),
        "plan_tier": str(billing.plan_tier),
        "cadence": str(billing.cadence),
        "quantity": billing.quantity,
        "current_period_end": (
            billing.current_period_end.isoformat() if billing.current_period_end else None
        ),
        "grace_until": billing.grace_until.isoformat() if billing.grace_until else None,
        "in_grace": is_in_grace(billing, now),
        "suspended": is_suspended(billing, now),
        "priority": effective_priority(billing),
        "has_subscription": billing.stripe_subscription_id is not None,
    }


# ── tenant-side counting + audit ────────────────────────────────────────────────
def active_subject_count(workspace_id: int) -> int:
    with tenant_session(schema_for_workspace(workspace_id)) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(Subject)
                .where(Subject.status == SubjectStatus.active)
            )
            or 0
        )


def _audit(
    workspace_id: int,
    action: str,
    *,
    actor_staff_id: int | None = None,
    meta: dict | None = None,
) -> None:
    with tenant_session(schema_for_workspace(workspace_id)) as session:
        record_audit(
            session,
            workspace_id=workspace_id,
            actor_staff_id=actor_staff_id,
            action=action,
            entity_type="billing",
            entity_id=str(workspace_id),
            meta=meta,
        )


# ── gates ────────────────────────────────────────────────────────────────────
def enforce_can_add_subject(workspace_id: int) -> None:
    """Raise BillingSuspended (→402) when a suspended workspace tries to add a NEW subject."""
    with public_session() as session:
        if is_suspended(get_or_create(session, workspace_id)):
            raise BillingSuspended(
                "This workspace's billing is suspended — new subjects are paused until billing is "
                "brought current. Existing cases, evidence and reports are unaffected."
            )


def discovery_allowed(workspace_id: int) -> bool:
    """False when a suspended workspace must not start NEW discovery jobs."""
    with public_session() as session:
        return not is_suspended(get_or_create(session, workspace_id))


def discovery_frequency_gate(workspace_id: int, configured: str) -> tuple[bool, str]:
    """(allowed, effective_frequency) for the scheduled-scan dispatcher, in one public read.

    Suspended → (False, 'off'). Otherwise the configured frequency clamped to the plan-allowed
    maximum (Core→weekly, Priority→daily, admin override wins; manual mode uncapped).
    """
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if is_suspended(billing):
            return (False, "off")
        return (True, cap_frequency(configured, effective_max_frequency(billing)))


# ── quantity sync (absolute, idempotent, drift-correcting) ──────────────────────
def sync_quantity(workspace_id: int, *, actor_staff_id: int | None = None) -> SyncResult:
    """Make the Stripe subscription quantity equal max(active_count, min). No-op unless stripe mode
    with a live subscription. Any observed quantity != desired is corrected and audited."""
    settings = get_settings()
    desired = desired_quantity(active_subject_count(workspace_id), settings)
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if (
            billing.billing_mode != BillingMode.stripe
            or billing.stripe_subscription_id is None
            or billing.status not in _ACTIVE_SUB_STATUSES
        ):
            return SyncResult(changed=False, observed=billing.quantity, desired=desired)
        client = get_billing_client()
        view = client.get_subscription(billing.stripe_subscription_id)
        observed = view.quantity
        if observed == desired:
            if billing.quantity != desired:
                billing.quantity = desired
                session.flush()
            return SyncResult(changed=False, observed=observed, desired=desired)
        client.set_subscription_quantity(billing.stripe_subscription_id, desired)
        billing.quantity = desired
        session.flush()
    _audit(
        workspace_id,
        "billing.quantity_corrected",
        actor_staff_id=actor_staff_id,
        meta={"observed": observed, "corrected_to": desired},
    )
    logger.info(
        "billing quantity corrected workspace=%s observed=%s corrected_to=%s",
        workspace_id,
        observed,
        desired,
    )
    return SyncResult(changed=True, observed=observed, desired=desired)


def enqueue_quantity_sync(session: Session, workspace_id: int) -> None:
    """Register an after-commit hook to sync quantity once the subject change is durable.

    Running AFTER commit (not inline) means the sync's fresh session sees the committed count — so
    it works identically under eager (test) and real Celery, and never fires on a rolled-back tx.
    """

    @event.listens_for(session, "after_commit", once=True)
    def _fire(_sess: Session) -> None:  # pragma: no cover - thin dispatch
        from worker.billing import sync_billing_quantity

        sync_billing_quantity.delay(workspace_id)


# ── mirror updates from Stripe ──────────────────────────────────────────────────
def apply_subscription_state(
    workspace_id: int, view: SubscriptionView, *, actor_staff_id: int | None = None
) -> None:
    """Recompute the mirror from a freshly-fetched Stripe subscription, then drift-correct qty."""
    settings = get_settings()
    tier, cadence = _price_map(settings).get(
        view.price_id or "", (PlanTier.none, BillingCadence.none)
    )
    try:
        status = BillingStatus(view.status)
    except ValueError:
        # Map Stripe's incomplete/unpaid/etc. onto our coarse states conservatively.
        status = BillingStatus.past_due if "due" in view.status else BillingStatus.none

    now = datetime.now(UTC)
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        prev_status = billing.status
        billing.stripe_subscription_id = view.id
        billing.status = status
        billing.plan_tier = tier
        billing.cadence = cadence
        billing.quantity = view.quantity
        billing.current_period_end = view.current_period_end
        if status == BillingStatus.past_due:
            # Stamp the FIRST time we see past_due; never reset on replay/re-fetch.
            if billing.past_due_since is None:
                billing.past_due_since = now
            billing.grace_until = billing.past_due_since + timedelta(
                days=settings.billing_grace_days
            )
        else:
            billing.past_due_since = None
            billing.grace_until = None
        session.flush()
    if prev_status != status:
        _audit(
            workspace_id,
            "billing.status_changed",
            actor_staff_id=actor_staff_id,
            meta={"from": str(prev_status), "to": str(status)},
        )
    sync_quantity(workspace_id, actor_staff_id=actor_staff_id)


# ── webhook ──────────────────────────────────────────────────────────────────
def _resolve_workspace_by_customer(customer_id: str | None) -> int | None:
    if not customer_id:
        return None
    with public_session() as session:
        return session.scalar(
            select(WorkspaceBilling.workspace_id).where(
                WorkspaceBilling.stripe_customer_id == customer_id
            )
        )


def _already_processed(event_id: str) -> bool:
    """True if this event id was already applied (replay). Read-only — does NOT record."""
    from api.app.models.billing import BillingEvent

    if not event_id:
        return False
    with public_session() as session:
        return session.get(BillingEvent, event_id) is not None


def _mark_processed(event_id: str, event_type: str) -> None:
    """Record the event id AFTER its state has been applied. Idempotent on a concurrent double
    delivery (the unique PK makes the second insert a no-op)."""
    from sqlalchemy.exc import IntegrityError

    from api.app.models.billing import BillingEvent

    if not event_id:
        return
    try:
        with public_session() as session:
            session.add(BillingEvent(stripe_event_id=event_id, type=event_type))
    except IntegrityError:
        pass  # another delivery of the same event recorded it first — fine (apply is idempotent)


def process_webhook(payload: bytes, signature: str) -> str:
    """Verify, dedupe, and apply a Stripe webhook. Raises SignatureError on a bad signature.

    Returns a short result string ('processed' | 'duplicate' | 'ignored'). Never trusts event
    payload STATE — it re-fetches the subscription from Stripe so out-of-order events can't regress.

    The event id is recorded **only after** the state has been applied, so a mid-processing failure
    (e.g. a Stripe timeout on the re-fetch) leaves the event UNrecorded — Stripe's retry reprocesses
    it rather than being swallowed as a duplicate. Apply is idempotent, so a reprocess is safe.
    """
    client = get_billing_client()
    event = client.construct_event(payload=payload, signature=signature)  # raises → 400
    if _already_processed(event.id):
        return "duplicate"

    obj = event.data_object
    customer_id = obj.get("customer")
    workspace_id = _resolve_workspace_by_customer(customer_id)
    if workspace_id is None:
        logger.warning("billing webhook for unknown customer=%s type=%s", customer_id, event.type)
        # Record it so an unmappable event isn't reprocessed forever; there is no state to apply.
        _mark_processed(event.id, event.type)
        return "ignored"

    if event.type == "checkout.session.completed" and obj.get("mode") == "payment":
        # The one-time onboarding audit payment.
        _audit(
            workspace_id,
            "billing.audit_payment_recorded",
            meta={"amount_total": obj.get("amount_total")},
        )
        _mark_processed(event.id, event.type)
        return "processed"

    if event.type == "checkout.session.completed":
        subscription_id = obj.get("subscription")
    else:
        # subscription.* events carry the sub as the object; invoice.* reference it.
        subscription_id = obj.get("id") if str(obj.get("object")) == "subscription" else None
        subscription_id = subscription_id or obj.get("subscription")

    if subscription_id:
        # If the re-fetch or apply raises, the event id is NOT recorded → Stripe retries.
        view = client.get_subscription(subscription_id)
        apply_subscription_state(workspace_id, view)
    _mark_processed(event.id, event.type)
    return "processed"


# ── staff-admin actions ─────────────────────────────────────────────────────────
def set_mode(workspace_id: int, *, actor_staff_id: int, mode: BillingMode) -> WorkspaceBilling:
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        billing.billing_mode = mode
        session.flush()
        session.expunge(billing)
    _audit(workspace_id, "billing.mode_changed", actor_staff_id=actor_staff_id,
           meta={"mode": str(mode)})
    return billing


def _ensure_customer(session: Session, billing: WorkspaceBilling) -> str:
    if billing.stripe_customer_id:
        return billing.stripe_customer_id
    workspace = session.get(Workspace, billing.workspace_id)
    if workspace is None:
        raise BillingError("workspace not found")
    cid = get_billing_client().create_customer(
        workspace_id=workspace.id, email=workspace.contact_email, name=workspace.name
    )
    billing.stripe_customer_id = cid
    session.flush()
    return cid


def create_checkout(
    workspace_id: int,
    *,
    actor_staff_id: int,
    plan_tier: PlanTier,
    cadence: BillingCadence,
    success_url: str,
    cancel_url: str,
) -> str:
    settings = get_settings()
    price_id = _price_for(settings, plan_tier, cadence)
    desired = desired_quantity(active_subject_count(workspace_id), settings)
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if billing.billing_mode != BillingMode.stripe:
            raise BillingError("set billing mode to 'stripe' before creating a checkout")
        customer_id = _ensure_customer(session, billing)
    session_out = get_billing_client().create_subscription_checkout(
        customer_id=customer_id,
        price_id=price_id,
        quantity=desired,
        success_url=success_url,
        cancel_url=cancel_url,
        automatic_tax=settings.stripe_automatic_tax,
    )
    _audit(workspace_id, "billing.checkout_created", actor_staff_id=actor_staff_id,
           meta={"plan_tier": str(plan_tier), "cadence": str(cadence)})
    return session_out.url


def create_onboarding_checkout(
    workspace_id: int, *, actor_staff_id: int, success_url: str, cancel_url: str
) -> str:
    settings = get_settings()
    if not settings.stripe_price_onboarding_audit:
        raise BillingError("no onboarding-audit price configured")
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if billing.billing_mode != BillingMode.stripe:
            raise BillingError("set billing mode to 'stripe' first")
        customer_id = _ensure_customer(session, billing)
    session_out = get_billing_client().create_payment_checkout(
        customer_id=customer_id,
        price_id=settings.stripe_price_onboarding_audit,
        success_url=success_url,
        cancel_url=cancel_url,
        automatic_tax=settings.stripe_automatic_tax,
    )
    _audit(workspace_id, "billing.onboarding_checkout_created", actor_staff_id=actor_staff_id)
    return session_out.url


def create_portal(workspace_id: int, *, actor_staff_id: int, return_url: str) -> str:
    settings = get_settings()
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if not billing.stripe_customer_id:
            raise BillingError("no Stripe customer yet — complete checkout first")
        customer_id = billing.stripe_customer_id
    url = get_billing_client().create_portal_session(
        customer_id=customer_id,
        configuration_id=settings.stripe_portal_configuration_id or None,
        return_url=return_url,
    )
    _audit(workspace_id, "billing.portal_opened", actor_staff_id=actor_staff_id)
    return url


def apply_onboarding_credit(workspace_id: int, *, actor_staff_id: int) -> WorkspaceBilling:
    """Credit the audit amount toward the first month — at most once per workspace (idempotent)."""
    settings = get_settings()
    if not settings.stripe_price_onboarding_audit:
        raise BillingError("no onboarding-audit price configured")
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if billing.onboarding_credit_applied_at is not None:
            session.expunge(billing)
            return billing  # already credited — no-op
        if not billing.stripe_customer_id:
            raise BillingError("no Stripe customer yet — complete checkout first")
        customer_id = billing.stripe_customer_id
        client = get_billing_client()
        amount = client.price_amount(settings.stripe_price_onboarding_audit)
        client.credit_customer_balance(
            customer_id=customer_id,
            amount=amount,
            idempotency_key=f"onboarding-credit:{workspace_id}",
        )
        billing.onboarding_credit_applied_at = datetime.now(UTC)
        session.flush()
        session.expunge(billing)
    _audit(workspace_id, "billing.onboarding_credited", actor_staff_id=actor_staff_id,
           meta={"amount": amount})
    return billing


def apply_design_partner_coupon(workspace_id: int, *, actor_staff_id: int) -> WorkspaceBilling:
    settings = get_settings()
    if not settings.stripe_coupon_design_partner:
        raise BillingError("no design-partner coupon configured")
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if not billing.stripe_subscription_id:
            raise BillingError("no active subscription to apply the coupon to")
        subscription_id = billing.stripe_subscription_id
    get_billing_client().apply_coupon(
        subscription_id=subscription_id, coupon_id=settings.stripe_coupon_design_partner
    )
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        billing.design_partner_coupon_applied_at = datetime.now(UTC)
        session.flush()
        session.expunge(billing)
    _audit(workspace_id, "billing.coupon_applied", actor_staff_id=actor_staff_id,
           meta={"coupon": settings.stripe_coupon_design_partner})
    return billing


def set_override(
    workspace_id: int,
    *,
    actor_staff_id: int,
    priority_override: bool | None,
    discovery_frequency_override: str | None,
) -> WorkspaceBilling:
    if discovery_frequency_override is not None and discovery_frequency_override not in _FREQ_RANK:
        raise BillingError("discovery_frequency_override must be off|weekly|daily")
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        billing.priority_override = priority_override
        billing.discovery_frequency_override = discovery_frequency_override
        session.flush()
        session.expunge(billing)
    _audit(
        workspace_id,
        "billing.override_changed",
        actor_staff_id=actor_staff_id,
        meta={
            "priority_override": priority_override,
            "discovery_frequency_override": discovery_frequency_override,
        },
    )
    return billing


def set_billing_contact(
    workspace_id: int, *, actor_staff_id: int, staff_id: int
) -> WorkspaceBilling:
    """Designate the one agency user who manages billing from the portal.

    The target MUST be an ``agency`` user with a grant to THIS workspace — so an agency user can
    never be made billing contact of a workspace it isn't in, and can never promote itself (only
    admins call this route).
    """
    with public_session() as session:
        target = session.get(Staff, staff_id)
        if target is None or target.role != StaffRole.agency:
            raise BillingError("billing contact must be an agency user")
        grant = session.scalar(
            select(StaffWorkspaceAccess).where(
                StaffWorkspaceAccess.staff_id == staff_id,
                StaffWorkspaceAccess.workspace_id == workspace_id,
            )
        )
        if grant is None:
            raise BillingError("that agency user has no access to this workspace")
        billing = get_or_create(session, workspace_id)
        billing.billing_contact_staff_id = staff_id
        session.flush()
        session.expunge(billing)
    _audit(workspace_id, "billing.contact_changed", actor_staff_id=actor_staff_id,
           meta={"staff_id": staff_id})
    return billing


# ── reconciliation (beat) ──────────────────────────────────────────────────────
def reconcile_workspace(workspace_id: int) -> bool:
    """Re-fetch the subscription, refresh status + quantity, log drift. Returns True if the fetched
    Stripe quantity differed from the derived value (i.e. drift was found and corrected)."""
    with public_session() as session:
        billing = get_or_create(session, workspace_id)
        if billing.billing_mode != BillingMode.stripe or billing.stripe_subscription_id is None:
            return False
        subscription_id = billing.stripe_subscription_id
    view = get_billing_client().get_subscription(subscription_id)
    desired = desired_quantity(active_subject_count(workspace_id))
    # Drift only counts for a billable subscription (a canceled sub has no quantity to correct).
    drifted = view.status in {s.value for s in _ACTIVE_SUB_STATUSES} and view.quantity != desired
    # apply_subscription_state refreshes status/period/past_due AND runs the quantity correction.
    apply_subscription_state(workspace_id, view)
    if drifted:
        logger.warning(
            "billing reconcile corrected drift workspace=%s observed=%s desired=%s",
            workspace_id,
            view.quantity,
            desired,
        )
    return drifted
