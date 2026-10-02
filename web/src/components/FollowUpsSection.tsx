import { useCallback, useEffect, useState } from "react";
import {
  type FollowUp,
  type MetricsSummary,
  type RemovalMetric,
  getMetricsSummary,
  getRemovalMetrics,
  listFollowUps,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { Card, EmptyState, Table, TD, TH, THead, TR } from "./ui";

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
      setError(errorText(e));
    }
  }, [getToken, workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="space-y-5" data-testid="followups-section">
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <Card title={`Follow-ups (${followUps.length})`} bodyClassName={followUps.length ? "p-4" : "p-4"}>
        {followUps.length === 0 ? (
          <EmptyState title="Nothing needs a nudge" description="Overdue filings will show up here." />
        ) : (
          <ul className="text-sm">
            {followUps.map((f) => (
              <li key={`${f.reason}:${f.case_id}`} className="border-t border-line py-1 first:border-0">
                <span className="font-mono">case #{f.case_id}</span> · {f.claim_type} ·{" "}
                <span className="text-fg-muted">{f.offender_key ?? "—"}</span> ·{" "}
                {f.reason === "removal_unverified" ? (
                  <span className="text-red-700 dark:text-red-400">
                    removal unverified — confirm or reopen
                  </span>
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">
                    due {f.due_at?.slice(0, 10) ?? "—"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Removal metrics (per platform × claim)" bodyClassName={metrics.length ? "p-0" : "p-4"}>
        {metrics.length === 0 ? (
          <EmptyState title="No filings yet" description="Metrics appear once notices are filed." />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>Platform</TH>
                <TH>Claim</TH>
                <TH>Filed</TH>
                <TH>Withdrawn</TH>
                <TH>Removed</TH>
                <TH title="removals a recheck observed gone">Verified</TH>
                <TH title="removals recorded by staff, never recheck-verified">Staff-only</TH>
                <TH>Pending</TH>
                <TH>Removal rate</TH>
                <TH>Median days</TH>
              </tr>
            </THead>
            <tbody>
              {metrics.map((m) => (
                <TR key={`${m.platform}:${m.claim_type}`}>
                  <TD>{m.platform}</TD>
                  <TD className="font-mono text-xs">{m.claim_type}</TD>
                  <TD>{m.filed}</TD>
                  <TD>{m.withdrawn}</TD>
                  <TD>{m.removed}</TD>
                  <TD>{m.removed_verified}</TD>
                  <TD>{m.removed_staff_only}</TD>
                  <TD>{m.pending}</TD>
                  <TD>{m.removal_rate == null ? "—" : `${Math.round(m.removal_rate * 100)}%`}</TD>
                  <TD>{m.median_days_to_removal == null ? "—" : m.median_days_to_removal}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {summary && (
        <Card title="Internal metrics" data-testid="metrics-summary">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-fg-muted" title="(filed − withdrawn) / filed">
                Review precision
              </dt>
              <dd>{pct(summary.review_precision)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted" title="withdrawn / filed">
                Wrong-filing rate
              </dt>
              <dd>{pct(summary.wrong_filing_rate)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted" title="reopened / removed">
                Re-upload rate
              </dt>
              <dd>{pct(summary.re_upload_rate)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted" title="median shown → decision">
                Review minutes / case
              </dt>
              <dd>
                {summary.review_minutes_per_case == null
                  ? "—"
                  : summary.review_minutes_per_case.toFixed(1)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">Provider cost</dt>
              <dd>${(summary.provider_cost_total_cents / 100).toFixed(2)}</dd>
            </div>
          </dl>
          {summary.provider_cost.length > 0 && (
            <p className="mt-2 text-xs text-fg-muted">
              {summary.provider_cost
                .map((c) => `${c.provider}: $${(c.cost_cents / 100).toFixed(2)}`)
                .join(" · ")}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
