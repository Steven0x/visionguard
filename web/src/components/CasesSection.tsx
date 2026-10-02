import { useCallback, useEffect, useState } from "react";
import {
  type CaseDetail,
  type CaseRow,
  type CaseStatus,
  type OffenderGroup,
  addCaseNote,
  assignCase,
  changeCaseClaim,
  clearCaseSensitive,
  getCaseDetail,
  listCasesFiltered,
  listOffenders,
  refileCase,
  transitionCase,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { CaseStatusBadge } from "./CaseStatusBadge";
import { EvidenceSection } from "./EvidenceSection";
import { NoticeSection } from "./NoticeSection";
import { OutcomesSection } from "./OutcomesSection";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Select,
  SkeletonRows,
  Table,
  TD,
  TH,
  THead,
  TR,
  Textarea,
} from "./ui";

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
  const [rows, setRows] = useState<CaseRow[] | null>(null);
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
      setError(errorText(e));
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

  if (rows === null) return <SkeletonRows rows={5} />;

  return (
    <Card
      data-testid="cases-section"
      bodyClassName="p-0"
      title={`Cases (${rows.length})`}
      actions={
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Select
            aria-label="Status filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">any status</option>
            {(
              [
                "confirmed",
                "filed",
                "removed",
                "countered",
                "escalated",
                "monitoring",
                "withdrawn",
                "recovered",
                "closed",
              ] as CaseStatus[]
            ).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            <input
              type="checkbox"
              checked={overdueOnly}
              onChange={(e) => setOverdueOnly(e.target.checked)}
            />
            overdue only
          </label>
          {offenderFilter && (
            <Button variant="ghost" size="sm" onClick={() => setOffenderFilter("")}>
              clear offender: {offenderFilter} ✕
            </Button>
          )}
        </div>
      }
    >
      {error && <p className="px-4 pt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {rows.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="No cases"
            description="Confirm a candidate in the review inbox to open a case."
          />
        </div>
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>Status</TH>
              <TH>Claim</TH>
              <TH>Offender</TH>
              <TH>Due</TH>
              <TH />
            </tr>
          </THead>
          <tbody>
            {rows.map((c) => (
              <TR key={c.id}>
                <TD>
                  <CaseStatusBadge row={c} />
                </TD>
                <TD className="font-mono text-xs">{c.claim_type}</TD>
                <TD className="text-fg-muted">{c.offender_key ?? "—"}</TD>
                <TD className="text-fg-muted">{c.due_at ? c.due_at.slice(0, 10) : "—"}</TD>
                <TD>
                  <Button variant="ghost" size="sm" onClick={() => setOpenId(c.id)}>
                    open
                  </Button>
                </TD>
              </TR>
            ))}
          </tbody>
        </Table>
      )}

      {offenders.length > 0 && (
        <div className="border-t border-line p-4">
          <h4 className="mb-2 text-xs font-medium text-fg-muted">By offender</h4>
          <ul className="flex flex-wrap gap-2 text-xs">
            {offenders.map((g) => (
              <li key={g.offender_key}>
                <button
                  className="rounded-md bg-surface-muted px-2 py-1 text-fg-muted hover:text-fg"
                  onClick={() => setOffenderFilter(g.offender_key)}
                >
                  {g.offender_key} · {g.open} open / {g.total}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
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
  const [busy, setBusy] = useState(false);
  const [noteTransition, setNoteTransition] = useState<CaseStatus | null>(null);
  const [transitionNote, setTransitionNote] = useState("");

  const reload = useCallback(async () => {
    try {
      setDetail(await getCaseDetail(await getToken(), workspaceId, caseId));
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
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const runTransition = (to: CaseStatus, note?: string) =>
    act(async () => transitionCase(await getToken(), workspaceId, caseId, to, { note }));

  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  if (!detail) return <SkeletonRows rows={5} />;
  const c = detail.case;

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Cases
      </Button>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold">Case #{c.id}</h3>
        <CaseStatusBadge row={c} />
        <span className="font-mono text-sm">{c.claim_type}</span>
      </div>

      <Card>
        <div className="space-y-1 text-sm text-fg-muted">
          <div>Offender: {c.offender_key ?? "—"}</div>
          <div>
            Source:{" "}
            {c.source_url ? (
              <a
                href={c.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
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
          <div className="flex items-center gap-2">
            Sensitive:{" "}
            {c.sensitive ? (
              <>
                <Badge tone="amber">yes — report thumbnails hidden</Badge>
                {c.claim_type !== "ncii" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      act(async () => clearCaseSensitive(await getToken(), workspaceId, caseId))
                    }
                  >
                    clear
                  </Button>
                )}
              </>
            ) : (
              <span>no</span>
            )}
          </div>
        </div>
      </Card>

      {/* Transitions — only those the state machine currently allows. */}
      <div className="flex flex-wrap gap-2">
        {detail.allowed_transitions.map((to) => (
          <Button
            key={to}
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => {
              if (NOTE_REQUIRED.includes(to)) {
                setNoteTransition(to);
                setTransitionNote("");
              } else {
                void runTransition(to);
              }
            }}
          >
            → {to}
          </Button>
        ))}
        {detail.allowed_transitions.length === 0 && (
          <span className="text-sm text-fg-muted">terminal — no transitions</span>
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
        onAssign={(sid) => act(async () => assignCase(await getToken(), workspaceId, caseId, sid))}
      />

      <EvidenceSection workspaceId={workspaceId} caseId={caseId} isAdmin={isAdmin} />
      <NoticeSection workspaceId={workspaceId} caseId={caseId} />
      <OutcomesSection
        workspaceId={workspaceId}
        caseId={caseId}
        caseStatus={c.status}
        onChanged={() => void reload()}
      />

      {/* Timeline */}
      <Card title="Timeline">
        <ul className="space-y-1 text-xs">
          {detail.timeline.map((e) => (
            <li key={e.id} className="border-t border-line py-1 first:border-0">
              <span className="text-fg-muted">
                {e.created_at.slice(0, 19).replace("T", " ")}
              </span>{" "}
              <span className="font-medium">{e.kind}</span>{" "}
              {e.from_status && (
                <span>
                  {e.from_status} → {e.to_status}
                </span>
              )}
              {e.related_case_id && <span> ↔ case #{e.related_case_id}</span>}
              {e.reason && <span className="text-fg-muted"> ({e.reason})</span>}
              {e.note && <span className="text-fg-muted"> — {e.note}</span>}
            </li>
          ))}
        </ul>
      </Card>

      {/* Notes (append-only) */}
      <Card title="Notes">
        <ul className="mb-2 space-y-1 text-sm">
          {detail.notes.map((n) => (
            <li key={n.id} className="border-t border-line py-1 first:border-0">
              <span className="text-fg-muted">{n.created_at.slice(0, 10)}</span> {n.body}
            </li>
          ))}
        </ul>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const input = e.currentTarget.elements.namedItem("body") as HTMLInputElement;
            if (input.value.trim()) {
              void act(async () => addCaseNote(await getToken(), workspaceId, caseId, input.value));
              e.currentTarget.reset();
            }
          }}
        >
          <Input name="body" aria-label="Add a note" placeholder="Add a note" className="flex-1" />
          <Button type="submit">Add</Button>
        </form>
      </Card>

      <Modal
        open={noteTransition !== null}
        onClose={() => setNoteTransition(null)}
        title={`Move to ${noteTransition ?? ""}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setNoteTransition(null)}>
              Cancel
            </Button>
            <Button
              disabled={!transitionNote.trim()}
              onClick={() => {
                const to = noteTransition;
                const note = transitionNote.trim();
                setNoteTransition(null);
                if (to) void runTransition(to, note);
              }}
            >
              Confirm
            </Button>
          </>
        }
      >
        <Textarea
          label="Note (required)"
          value={transitionNote}
          onChange={(e) => setTransitionNote(e.target.value)}
          autoFocus
        />
      </Modal>
    </div>
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
    <Card className="max-w-xl" bodyClassName="p-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          const claim = String(form.get("claim") ?? "");
          const note = String(form.get("note") ?? "");
          if (note.trim()) void onSubmit(claim, note);
        }}
      >
        <span className="text-sm text-fg-muted">{label}:</span>
        <Select name="claim" aria-label="Claim type">
          {CLAIM_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
        <Input name="note" required aria-label="Note" placeholder="note (required)" />
        <Button type="submit" variant="secondary">
          {label}
        </Button>
      </form>
    </Card>
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
      <span className="text-fg-muted">Assign to staff id:</span>
      <Input name="staff_id" aria-label="Staff id" className="w-28" placeholder="(blank = none)" />
      <Button type="submit" variant="secondary">
        Assign
      </Button>
    </form>
  );
}
