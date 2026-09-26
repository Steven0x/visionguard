import { useCallback, useEffect, useState } from "react";
import {
  type CaseDetail,
  type CaseRow,
  type CaseStatus,
  type OffenderGroup,
  addCaseNote,
  assignCase,
  changeCaseClaim,
  getCaseDetail,
  listCasesFiltered,
  listOffenders,
  refileCase,
  transitionCase,
} from "../api";
import { useToken } from "../useToken";
import { CaseStatusBadge } from "./CaseStatusBadge";
import { EvidenceSection } from "./EvidenceSection";

const CLAIM_TYPES = ["copyright", "likeness", "ncii", "impersonation", "trademark"];
const NOTE_REQUIRED: CaseStatus[] = ["withdrawn"];

export function CasesSection({
  workspaceId,
  isAdmin,
}: {
  workspaceId: number;
  isAdmin: boolean;
}) {
  const getToken = useToken();
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [offenders, setOffenders] = useState<OffenderGroup[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [offenderFilter, setOffenderFilter] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const t = await getToken();
      setRows(
        await listCasesFiltered(t, workspaceId, {
          status: (statusFilter || undefined) as CaseStatus | undefined,
          overdue: overdueOnly || undefined,
          offender_key: offenderFilter || undefined,
        }),
      );
      setOffenders(await listOffenders(t, workspaceId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, statusFilter, overdueOnly, offenderFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (openId !== null) {
    return (
      <CaseDetailView
        workspaceId={workspaceId}
        caseId={openId}
        isAdmin={isAdmin}
        onBack={() => {
          setOpenId(null);
          void reload();
        }}
      />
    );
  }

  return (
    <section className="space-y-3 rounded border border-gray-200 p-3" data-testid="cases-section">
      <h3 className="font-medium">Cases ({rows.length})</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border p-1"
        >
          <option value="">any status</option>
          {(
            ["confirmed", "filed", "removed", "countered", "escalated", "monitoring", "withdrawn", "recovered", "closed"] as CaseStatus[]
          ).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label>
          <input
            type="checkbox"
            checked={overdueOnly}
            onChange={(e) => setOverdueOnly(e.target.checked)}
          />{" "}
          overdue only
        </label>
        {offenderFilter && (
          <button className="text-blue-700" onClick={() => setOffenderFilter("")}>
            clear offender: {offenderFilter} ✕
          </button>
        )}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="p-1">Status</th>
            <th className="p-1">Claim</th>
            <th className="p-1">Offender</th>
            <th className="p-1">Due</th>
            <th className="p-1"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} className="border-t border-gray-100">
              <td className="p-1">
                <CaseStatusBadge row={c} />
              </td>
              <td className="p-1 font-mono">{c.claim_type}</td>
              <td className="p-1 text-gray-600">{c.offender_key ?? "—"}</td>
              <td className="p-1 text-gray-400">{c.due_at ? c.due_at.slice(0, 10) : "—"}</td>
              <td className="p-1">
                <button className="text-blue-700" onClick={() => setOpenId(c.id)}>
                  open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <h4 className="text-sm font-medium">By offender</h4>
        <ul className="flex flex-wrap gap-2 text-xs">
          {offenders.map((g) => (
            <li key={g.offender_key}>
              <button
                className="rounded bg-gray-100 px-2 py-0.5 text-gray-700"
                onClick={() => setOffenderFilter(g.offender_key)}
              >
                {g.offender_key} · {g.open} open / {g.total}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function CaseDetailView({
  workspaceId,
  caseId,
  isAdmin,
  onBack,
}: {
  workspaceId: number;
  caseId: number;
  isAdmin: boolean;
  onBack: () => void;
}) {
  const getToken = useToken();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setDetail(await getCaseDetail(await getToken(), workspaceId, caseId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, caseId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const runTransition = (to: CaseStatus, note?: string) =>
    act(async () => transitionCase(await getToken(), workspaceId, caseId, to, { note }));

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!detail) return <p className="text-gray-500">Loading…</p>;
  const c = detail.case;

  return (
    <section className="space-y-4">
      <button className="text-sm text-blue-700" onClick={onBack}>
        ← Cases
      </button>
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold">Case #{c.id}</h3>
        <CaseStatusBadge row={c} />
        <span className="font-mono text-sm">{c.claim_type}</span>
      </div>

      <div className="text-sm text-gray-600">
        <div>Offender: {c.offender_key ?? "—"}</div>
        <div>
          Source:{" "}
          {c.source_url ? (
            <a
              href={c.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-700"
            >
              {c.source_url}
            </a>
          ) : (
            "—"
          )}
        </div>
        <div>
          Candidate #{c.candidate_id ?? "—"} · matched asset #{c.matched_asset_id ?? "—"} ·
          assignee {c.assigned_staff_id ?? "—"}
        </div>
      </div>

      {/* Transitions — only those the state machine currently allows. */}
      <div className="flex flex-wrap gap-2">
        {detail.allowed_transitions.map((to) => (
          <button
            key={to}
            className="rounded bg-gray-800 px-2 py-1 text-sm text-white"
            onClick={() => {
              if (NOTE_REQUIRED.includes(to)) {
                const note = window.prompt(`Note for moving to ${to} (required):`) ?? "";
                if (note.trim()) void runTransition(to, note);
              } else {
                void runTransition(to);
              }
            }}
          >
            → {to}
          </button>
        ))}
        {detail.allowed_transitions.length === 0 && (
          <span className="text-sm text-gray-400">terminal — no transitions</span>
        )}
      </div>

      {/* Claim change (pre-filed) or re-file (withdrawn). */}
      {(c.status === "confirmed" || c.status === "discovered") && (
        <ClaimForm
          label="Change claim"
          onSubmit={(claim, note) =>
            act(async () => changeCaseClaim(await getToken(), workspaceId, caseId, claim, note))
          }
        />
      )}
      {c.status === "withdrawn" && (
        <ClaimForm
          label="Re-file as new case"
          onSubmit={(claim, note) =>
            act(async () => refileCase(await getToken(), workspaceId, caseId, claim, note))
          }
        />
      )}

      <Assign
        onAssign={(sid) =>
          act(async () => assignCase(await getToken(), workspaceId, caseId, sid))
        }
      />

      <EvidenceSection workspaceId={workspaceId} caseId={caseId} isAdmin={isAdmin} />

      {/* Timeline */}
      <div>
        <h4 className="font-medium">Timeline</h4>
        <ul className="space-y-1 text-xs">
          {detail.timeline.map((e) => (
            <li key={e.id} className="border-t border-gray-100 py-1">
              <span className="text-gray-400">{e.created_at.slice(0, 19).replace("T", " ")}</span>{" "}
              <span className="font-medium">{e.kind}</span>{" "}
              {e.from_status && <span>{e.from_status} → {e.to_status}</span>}
              {e.related_case_id && <span> ↔ case #{e.related_case_id}</span>}
              {e.reason && <span className="text-gray-500"> ({e.reason})</span>}
              {e.note && <span className="text-gray-600"> — {e.note}</span>}
            </li>
          ))}
        </ul>
      </div>

      {/* Notes (append-only) */}
      <div>
        <h4 className="font-medium">Notes</h4>
        <ul className="space-y-1 text-sm">
          {detail.notes.map((n) => (
            <li key={n.id} className="border-t border-gray-100 py-1">
              <span className="text-gray-400">{n.created_at.slice(0, 10)}</span> {n.body}
            </li>
          ))}
        </ul>
        <form
          className="mt-1 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const input = e.currentTarget.elements.namedItem("body") as HTMLInputElement;
            if (input.value.trim()) {
              void act(async () => addCaseNote(await getToken(), workspaceId, caseId, input.value));
              e.currentTarget.reset();
            }
          }}
        >
          <input name="body" placeholder="Add a note" className="flex-1 border p-1 text-sm" />
          <button className="rounded bg-blue-700 px-2 py-1 text-sm text-white">Add</button>
        </form>
      </div>
    </section>
  );
}

function ClaimForm({
  label,
  onSubmit,
}: {
  label: string;
  onSubmit: (claim: string, note: string) => Promise<void>;
}) {
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded bg-gray-50 p-2"
      onSubmit={(e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const claim = String(form.get("claim") ?? "");
        const note = String(form.get("note") ?? "");
        if (note.trim()) void onSubmit(claim, note);
      }}
    >
      <span className="text-sm text-gray-600">{label}:</span>
      <select name="claim" className="border p-1 text-sm">
        {CLAIM_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <input name="note" required placeholder="note (required)" className="border p-1 text-sm" />
      <button className="rounded bg-gray-800 px-2 py-1 text-sm text-white">{label}</button>
    </form>
  );
}

function Assign({ onAssign }: { onAssign: (staffId: number | null) => Promise<void> }) {
  return (
    <form
      className="flex items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const raw = String(form.get("staff_id") ?? "").trim();
        void onAssign(raw ? Number(raw) : null);
      }}
    >
      <span className="text-gray-600">Assign to staff id:</span>
      <input name="staff_id" className="w-24 border p-1" placeholder="(blank = none)" />
      <button className="rounded bg-gray-700 px-2 py-1 text-white">Assign</button>
    </form>
  );
}
