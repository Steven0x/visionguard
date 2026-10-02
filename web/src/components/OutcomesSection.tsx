import { useCallback, useEffect, useState } from "react";
import {
  type CaseStatus,
  type OutcomeKind,
  type OutcomesDetail,
  type UrlRecheckRow,
  dismissRemovalProposal,
  getOutcomes,
  listRechecks,
  recordOutcome,
  reopenCase,
  transitionCase,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";

const OUTCOMES: { value: OutcomeKind; label: string; hint: string }[] = [
  { value: "removed", label: "Removed", hint: "content taken down → case Removed" },
  { value: "rejected", label: "Rejected", hint: "platform refused → escalate or withdraw next" },
  { value: "countered", label: "Countered", hint: "counter-notice → case Countered" },
  { value: "no_response", label: "No response", hint: "window elapsed → nudge again" },
];

export function OutcomesSection({
  workspaceId,
  caseId,
  caseStatus,
  onChanged,
}: {
  workspaceId: number;
  caseId: number;
  caseStatus: CaseStatus;
  onChanged: () => void;
}) {
  const getToken = useToken();
  const [detail, setDetail] = useState<OutcomesDetail | null>(null);
  const [rechecks, setRechecks] = useState<UrlRecheckRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const t = await getToken();
      setDetail(await getOutcomes(t, workspaceId, caseId));
      setRechecks(await listRechecks(t, workspaceId, caseId));
    } catch (e) {
      setError(errorText(e));
    }
  }, [getToken, workspaceId, caseId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const act = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await fn();
      await reload();
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const record = (outcome: OutcomeKind) =>
    act(async () => recordOutcome(await getToken(), workspaceId, caseId, { outcome }));

  return (
    <section className="space-y-2" data-testid="outcomes-section">
      <h4 className="font-medium">Outcome &amp; watch</h4>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Auto-proposed removal (Filed) — a human confirms or dismisses; nothing auto-transitions. */}
      {detail?.removal_proposed_at && caseStatus === "filed" && (
        <div className="space-y-1 rounded bg-amber-50 p-2 text-xs text-amber-800">
          <div>
            The URL re-check proposes this was <strong>removed</strong> (two consistent 404s ≥24h
            apart). Confirm to seal removal proof, or dismiss if it&apos;s still up.
          </div>
          <div className="flex gap-2">
            <button
              disabled={busy}
              className="rounded bg-green-700 px-2 py-1 text-white disabled:opacity-50"
              onClick={() => void record("removed")}
            >
              Confirm removed
            </button>
            <button
              disabled={busy}
              className="rounded bg-gray-600 px-2 py-1 text-white disabled:opacity-50"
              onClick={() => {
                const note = window.prompt("Why is this a false positive? (required)") ?? "";
                if (note.trim())
                  void act(async () =>
                    dismissRemovalProposal(await getToken(), workspaceId, caseId, note),
                  );
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Unverified removal (Monitoring) — every recheck stayed live (soft-404). A human must
          confirm-close or reopen; it is never auto-closed. */}
      {detail?.removal_unverified_at && caseStatus === "monitoring" && (
        <div className="space-y-1 rounded bg-red-50 p-2 text-xs text-red-800">
          <div>
            Removal <strong>unverified</strong>: the URL kept serving a page after the take-down
            (a soft-404 platform). Confirm it&apos;s really down (close), or reopen.
          </div>
          <div className="flex gap-2">
            <button
              disabled={busy}
              className="rounded bg-gray-700 px-2 py-1 text-white disabled:opacity-50"
              onClick={() =>
                void act(async () =>
                  transitionCase(await getToken(), workspaceId, caseId, "closed", {
                    reason: "removal_confirmed",
                  }),
                )
              }
            >
              Confirm &amp; close
            </button>
            <button
              disabled={busy}
              className="rounded bg-orange-700 px-2 py-1 text-white disabled:opacity-50"
              onClick={() => void act(async () => reopenCase(await getToken(), workspaceId, caseId))}
            >
              Reopen
            </button>
          </div>
        </div>
      )}

      {/* Reappearance (Monitoring) — a human confirms the reopen. */}
      {detail?.reappearance_proposed_at && caseStatus === "monitoring" && (
        <div className="space-y-1 rounded bg-orange-50 p-2 text-xs text-orange-800">
          <div>
            The re-check saw this monitored URL go live again (gone → live). Reopen the case?
          </div>
          <button
            disabled={busy}
            className="rounded bg-orange-700 px-2 py-1 text-white disabled:opacity-50"
            onClick={() => void act(async () => reopenCase(await getToken(), workspaceId, caseId))}
          >
            Reopen case
          </button>
        </div>
      )}

      {/* Record an outcome on a filed case. */}
      {caseStatus === "filed" && (
        <div className="flex flex-wrap gap-2">
          {OUTCOMES.map((o) => (
            <button
              key={o.value}
              disabled={busy}
              title={o.hint}
              className="rounded bg-gray-800 px-2 py-1 text-xs text-white disabled:opacity-50"
              onClick={() => void record(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}

      {/* After a rejection, the next move is escalate (re-file) or withdraw — via the case
          transition buttons above; this just reminds staff. */}
      {detail?.effective_outcome === "rejected" && caseStatus === "filed" && (
        <p className="rounded bg-surface-muted p-2 text-xs text-fg-muted">
          Rejected by the platform. Next: escalate (re-file) or withdraw using the case
          transitions above.
        </p>
      )}

      {/* Recorded outcomes. */}
      {detail && detail.outcomes.length > 0 && (
        <ul className="space-y-1 text-xs">
          {detail.outcomes.map((o) => (
            <li key={o.id} className="border-t border-line py-1">
              <span className="font-medium">{o.outcome}</span>{" "}
              <span className="text-fg-muted">effective {o.effective_at}</span>{" "}
              <span className="text-fg-muted">({o.source})</span>
              {o.supersedes_id && <span className="text-fg-muted"> — corrects #{o.supersedes_id}</span>}
              {o.note && <span className="text-fg-muted"> — {o.note}</span>}
            </li>
          ))}
        </ul>
      )}

      {/* Re-check history. */}
      {rechecks.length > 0 && (
        <details className="text-xs text-fg-muted">
          <summary>URL re-checks ({rechecks.length})</summary>
          <ul className="mt-1 space-y-0.5">
            {rechecks.map((r) => (
              <li key={r.id}>
                <span className="text-fg-muted">{r.created_at.slice(0, 19).replace("T", " ")}</span>{" "}
                <span className="font-mono">{r.result}</span>
                {r.http_status != null && <span> ({r.http_status})</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
