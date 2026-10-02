"""Billing Celery tasks (Slice 13).

``sync_billing_quantity`` is enqueued after a subject is added/archived/reactivated and sets the
Stripe subscription quantity to max(active, min) — absolute and idempotent, so a lost/duplicated
enqueue can't corrupt the count. ``reconcile_billing`` is the daily safety net: for every
stripe-mode workspace it re-fetches the subscription, re-syncs quantity + status, and logs drift.
Both NEVER raise: a bad workspace is skipped, not fatal.
"""

from __future__ import annotations

import logging

from api.app.db.session import public_session
from api.app.models.billing import BillingMode, WorkspaceBilling
from api.app.services import billing as billing_svc
from sqlalchemy import select

from worker.celery_app import celery
from worker.locks import single_run

logger = logging.getLogger("visionguard.worker.billing")


@celery.task(name="worker.sync_billing_quantity")
def sync_billing_quantity(workspace_id: int) -> bool:
    """Set the subscription quantity for one workspace from its live active-subject count."""
    try:
        return billing_svc.sync_quantity(workspace_id).changed
    except Exception:  # noqa: BLE001 - a billing hiccup must never break a subject write
        logger.exception("sync_billing_quantity failed for workspace=%s", workspace_id)
        return False


@celery.task(name="worker.reconcile_billing")
@single_run("reconcile-billing")
def reconcile_billing() -> int:
    """Beat: reconcile every stripe-mode workspace to Stripe. Returns the count corrected."""
    with public_session() as session:
        workspace_ids = list(
            session.scalars(
                select(WorkspaceBilling.workspace_id).where(
                    WorkspaceBilling.billing_mode == BillingMode.stripe
                )
            ).all()
        )
    corrected = 0
    for workspace_id in workspace_ids:
        try:
            if billing_svc.reconcile_workspace(workspace_id):
                corrected += 1
        except Exception:  # noqa: BLE001 - skip a bad workspace, keep reconciling the rest
            logger.exception("reconcile_billing failed for workspace=%s", workspace_id)
    return corrected
