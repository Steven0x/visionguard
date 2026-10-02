import { useCallback, useEffect, useState } from "react";
import {
  applyDesignPartnerCoupon,
  applyOnboardingCredit,
  createBillingCheckout,
  getBilling,
  openBillingPortal,
  setBillingMode,
  type BillingCadence,
  type BillingMode,
  type BillingPlanTier,
  type BillingStatus,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";

/** Staff-admin billing management for one workspace. Pricing lives in Stripe; this panel only sets
 * the billing mode, opens hosted Checkout / Customer Portal, and applies the onboarding credit /
 * design-partner coupon. Quantity is derived server-side from the active-subject count. */
export function BillingPanel({ workspaceId }: { workspaceId: number }) {
  const getToken = useToken();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [plan, setPlan] = useState<BillingPlanTier>("core");
  const [cadence, setCadence] = useState<BillingCadence>("monthly");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setBilling(await getBilling(await getToken(), workspaceId));
    } catch (e) {
      setError(errorText(e));
    }
  }, [getToken, workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = async (fn: (token: string) => Promise<unknown>, note?: string) => {
    setMsg(null);
    setError(null);
    try {
      await fn(await getToken());
      if (note) setMsg(note);
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const openHosted = async (fn: (token: string) => Promise<{ url: string }>) => {
    setError(null);
    try {
      const { url } = await fn(await getToken());
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setError(errorText(e));
    }
  };

  if (!billing)
    return (
      <section className="rounded border border-line p-3 text-sm text-fg-muted">
        Loading billing…
      </section>
    );

  return (
    <section className="space-y-3 rounded border border-line p-3">
      <h3 className="font-medium">Billing</h3>

      {billing.suspended && (
        <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          Suspended — new subjects and new discovery are paused. Existing filed work is unaffected.
        </p>
      )}
      {billing.in_grace && (
        <p className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-800">
          Past due — in grace until {billing.grace_until?.slice(0, 10) ?? "?"}.
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-fg-muted">Status</dt>
        <dd>{billing.status}</dd>
        <dt className="text-fg-muted">Plan</dt>
        <dd>
          {billing.plan_tier} ({billing.cadence})
        </dd>
        <dt className="text-fg-muted">Talents billed</dt>
        <dd>{billing.quantity}</dd>
        <dt className="text-fg-muted">Renews</dt>
        <dd>{billing.current_period_end?.slice(0, 10) ?? "—"}</dd>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-fg-muted">Mode</label>
        <select
          className="border p-1 text-sm"
          value={billing.billing_mode}
          onChange={(e) =>
            void run((t) => setBillingMode(t, workspaceId, e.target.value as BillingMode))
          }
        >
          <option value="manual">manual</option>
          <option value="stripe">stripe</option>
        </select>
      </div>

      {billing.billing_mode === "stripe" && (
        <div className="space-y-2 border-t border-line pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="border p-1 text-sm"
              value={plan}
              onChange={(e) => setPlan(e.target.value as BillingPlanTier)}
            >
              <option value="core">Core</option>
              <option value="priority">Priority</option>
            </select>
            <select
              className="border p-1 text-sm"
              value={cadence}
              onChange={(e) => setCadence(e.target.value as BillingCadence)}
            >
              <option value="monthly">Monthly</option>
              <option value="annual">Annual</option>
            </select>
            <button
              className="rounded bg-primary px-2 py-1 text-sm text-white"
              onClick={() =>
                void openHosted((t) => createBillingCheckout(t, workspaceId, plan, cadence))
              }
            >
              Checkout
            </button>
            <button
              className="rounded border border-line px-2 py-1 text-sm"
              onClick={() => void openHosted((t) => openBillingPortal(t, workspaceId))}
            >
              Customer Portal
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded border border-line px-2 py-1 text-sm"
              onClick={() =>
                void run(
                  (t) => applyOnboardingCredit(t, workspaceId),
                  "Onboarding credit applied.",
                )
              }
            >
              Credit onboarding audit
            </button>
            <button
              className="rounded border border-line px-2 py-1 text-sm"
              onClick={() =>
                void run(
                  (t) => applyDesignPartnerCoupon(t, workspaceId),
                  "Design-partner coupon applied.",
                )
              }
            >
              Apply design-partner coupon
            </button>
          </div>
        </div>
      )}
      {msg && <p className="text-xs text-green-700">{msg}</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </section>
  );
}
