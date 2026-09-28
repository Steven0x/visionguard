import { useCallback, useEffect, useState } from "react";
import {
  type FollowUp,
  type MetricsSummary,
  type RemovalMetric,
  getMetricsSummary,
  getRemovalMetrics,
  listFollowUps,
} from "../api";
import { useToken } from "../useToken";

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export function FollowUpsSection({ workspaceId }: { workspaceId: number }) {
  const getToken = useToken();
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [metrics, setMetrics] = useState<RemovalMetric[]>([]);
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const t = await getToken();
      setFollowUps(await listFollowUps(t, workspaceId));
      setMetrics(await getRemovalMetrics(t, workspaceId));
      setSummary(await getMetricsSummary(t, workspaceId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <section
      className="space-y-3 rounded border border-gray-200 p-3"
      data-testid="followups-section"
    >
      <h3 className="font-medium">Follow-ups &amp; removal metrics</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div>
        <h4 className="text-sm font-medium">Follow-ups ({followUps.length})</h4>
        {followUps.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing needs a nudge right now.</p>
        ) : (
          <ul className="text-sm">
            {followUps.map((f) => (
              <li key={`${f.reason}:${f.case_id}`} className="border-t border-gray-100 py-1">
                <span className="font-mono">case #{f.case_id}</span> · {f.claim_type} ·{" "}
                <span className="text-gray-600">{f.offender_key ?? "—"}</span> ·{" "}
                {f.reason === "removal_unverified" ? (
                  <span className="text-red-700">removal unverified — confirm or reopen</span>
                ) : (
                  <span className="text-amber-700">due {f.due_at?.slice(0, 10) ?? "—"}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="text-sm font-medium">Removal metrics (per platform × claim)</h4>
        {metrics.length === 0 ? (
          <p className="text-sm text-gray-400">No filings yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="p-1">Platform</th>
                <th className="p-1">Claim</th>
                <th className="p-1">Filed</th>
                <th className="p-1">Withdrawn</th>
                <th className="p-1">Removed</th>
                <th className="p-1" title="removals a recheck observed gone">Verified</th>
                <th className="p-1" title="removals recorded by staff, never recheck-verified">
                  Staff-only
                </th>
                <th className="p-1">Pending</th>
                <th className="p-1">Removal rate</th>
                <th className="p-1">Median days</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={`${m.platform}:${m.claim_type}`} className="border-t border-gray-100">
                  <td className="p-1">{m.platform}</td>
                  <td className="p-1 font-mono">{m.claim_type}</td>
                  <td className="p-1">{m.filed}</td>
                  <td className="p-1">{m.withdrawn}</td>
                  <td className="p-1">{m.removed}</td>
                  <td className="p-1">{m.removed_verified}</td>
                  <td className="p-1">{m.removed_staff_only}</td>
                  <td className="p-1">{m.pending}</td>
                  <td className="p-1">
                    {m.removal_rate == null ? "—" : `${Math.round(m.removal_rate * 100)}%`}
                  </td>
                  <td className="p-1">
                    {m.median_days_to_removal == null ? "—" : m.median_days_to_removal}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {summary && (
        <div data-testid="metrics-summary">
          <h4 className="text-sm font-medium">Internal metrics</h4>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-gray-500" title="(filed − withdrawn) / filed">
                Review precision
              </dt>
              <dd>{pct(summary.review_precision)}</dd>
            </div>
            <div>
              <dt className="text-gray-500" title="withdrawn / filed">
                Wrong-filing rate
              </dt>
              <dd>{pct(summary.wrong_filing_rate)}</dd>
            </div>
            <div>
              <dt className="text-gray-500" title="reopened / removed">
                Re-upload rate
              </dt>
              <dd>{pct(summary.re_upload_rate)}</dd>
            </div>
            <div>
              <dt className="text-gray-500" title="median shown → decision">
                Review minutes / case
              </dt>
              <dd>
                {summary.review_minutes_per_case == null
                  ? "—"
                  : summary.review_minutes_per_case.toFixed(1)}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Provider cost</dt>
              <dd>${(summary.provider_cost_total_cents / 100).toFixed(2)}</dd>
            </div>
          </dl>
          {summary.provider_cost.length > 0 && (
            <p className="mt-1 text-xs text-gray-500">
              {summary.provider_cost
                .map((c) => `${c.provider}: $${(c.cost_cents / 100).toFixed(2)}`)
                .join(" · ")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
