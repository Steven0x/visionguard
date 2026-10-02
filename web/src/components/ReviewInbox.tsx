import { useCallback, useEffect, useRef, useState } from "react";
import {
  DISMISS_REASONS,
  type DismissReason,
  type InboxItem,
  assetMatchThumbnailUrl,
  bulkDismiss,
  confirmCandidate,
  dismissCandidate,
  foundThumbnailUrl,
  listInbox,
  reopenCandidate,
  updateReviewPrefs,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { ScoreBadge } from "./ScoreBadge";
import {
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Select,
  SkeletonRows,
  Textarea,
} from "./ui";

type ThumbKind = "found" | "asset";

/** A signed-URL thumbnail; found content is blurred until revealed (CLAUDE.md #7). No autoplay:
 *  static <img> only. */
function Thumb({
  workspaceId,
  candidateId,
  kind,
  blur,
}: {
  workspaceId: number;
  candidateId: number;
  kind: ThumbKind;
  blur: boolean;
}) {
  const getToken = useToken();
  const [url, setUrl] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        const r =
          kind === "found"
            ? await foundThumbnailUrl(token, workspaceId, candidateId)
            : await assetMatchThumbnailUrl(token, workspaceId, candidateId);
        if (active) setUrl(r.url);
      } catch {
        /* no thumbnail */
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken, workspaceId, candidateId, kind]);

  if (!url) {
    return (
      <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-surface-muted text-[10px] text-fg-muted">
        {kind === "asset" ? "no match" : "link"}
      </div>
    );
  }
  const hidden = kind === "found" && blur && !revealed;
  return (
    <button
      type="button"
      className="relative h-16 w-16 overflow-hidden rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
      title={hidden ? "click to reveal" : undefined}
      onClick={() => kind === "found" && setRevealed((v) => !v)}
    >
      <img
        src={url}
        alt={kind}
        className={`h-16 w-16 object-cover ${hidden ? "blur-lg" : ""}`}
        data-testid={`thumb-${kind}`}
      />
      {hidden && (
        <span className="absolute inset-0 flex items-center justify-center text-[10px] text-white">
          reveal
        </span>
      )}
    </button>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-fg-muted ring-1 ring-inset ring-line">
      {children}
    </kbd>
  );
}

export function ReviewInbox({
  workspaceId,
  isAdmin,
  keepBlurDefault,
}: {
  workspaceId: number;
  isAdmin: boolean;
  keepBlurDefault: boolean;
}) {
  const getToken = useToken();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [selected, setSelected] = useState(0);
  const [keepBlur, setKeepBlur] = useState(keepBlurDefault);
  const [claimByItem, setClaimByItem] = useState<Record<number, string>>({});
  const [reasonByItem, setReasonByItem] = useState<Record<number, DismissReason>>({});
  const [bulkDomain, setBulkDomain] = useState("");
  const [bulkReason, setBulkReason] = useState<DismissReason>("not_a_match");
  const [bulkPreview, setBulkPreview] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [reopenId, setReopenId] = useState<number | null>(null);
  const [reopenNote, setReopenNote] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const token = await getToken();
      const filters: Record<string, unknown> = {};
      if (minScore) filters.min_score = Number(minScore);
      if (domainFilter) filters.domain = domainFilter.trim();
      const rows = await listInbox(token, workspaceId, filters);
      setItems(rows);
      setSelected((s) => Math.min(s, Math.max(0, rows.length - 1)));
    } catch (e) {
      setError(errorText(e));
    }
  }, [getToken, workspaceId, minScore, domainFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const rows = items ?? [];
  const claimFor = (it: InboxItem) =>
    claimByItem[it.id] ?? it.suggested_claim ?? it.supported_claims[0] ?? "";
  const reasonFor = (it: InboxItem) => reasonByItem[it.id] ?? "not_a_match";

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

  const doConfirm = async (it: InboxItem) => {
    const claim = claimFor(it);
    if (!claim) {
      setError("No supported claim for this subject — add rights/consent first.");
      return;
    }
    await act(async () => confirmCandidate(await getToken(), workspaceId, it.id, claim));
  };
  const doDismiss = async (it: InboxItem) =>
    act(async () => dismissCandidate(await getToken(), workspaceId, it.id, reasonFor(it)));
  const submitReopen = async () => {
    if (reopenId === null || !reopenNote.trim()) return;
    const id = reopenId;
    const note = reopenNote.trim();
    setReopenId(null);
    setReopenNote("");
    await act(async () => reopenCandidate(await getToken(), workspaceId, id, note));
  };

  // Keyboard: J/K move, C confirm, D dismiss.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (rows.length === 0) return;
    const it = rows[selected];
    if (e.key === "j" || e.key === "J") setSelected((s) => Math.min(rows.length - 1, s + 1));
    else if (e.key === "k" || e.key === "K") setSelected((s) => Math.max(0, s - 1));
    else if ((e.key === "c" || e.key === "C") && it) void doConfirm(it);
    else if ((e.key === "d" || e.key === "D") && it) void doDismiss(it);
  };

  const toggleKeepBlur = async (v: boolean) => {
    setKeepBlur(v);
    try {
      await updateReviewPrefs(await getToken(), v);
    } catch {
      /* preference is best-effort */
    }
  };

  const previewBulk = async () => {
    setError(null);
    try {
      const r = await bulkDismiss(await getToken(), workspaceId, {
        domain: bulkDomain.trim(),
        reason: bulkReason,
        dry_run: true,
      });
      setBulkPreview(r.count);
    } catch (e) {
      setError(errorText(e));
    }
  };
  const applyBulk = () =>
    act(async () => {
      await bulkDismiss(await getToken(), workspaceId, {
        domain: bulkDomain.trim(),
        reason: bulkReason,
        dry_run: false,
      });
      setBulkPreview(null);
      setBulkDomain("");
    });

  if (items === null) return <SkeletonRows rows={5} />;

  return (
    <Card
      bodyClassName="p-0"
      title={`Review inbox (${rows.length})`}
      actions={
        <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
          <Kbd>J</Kbd>
          <Kbd>K</Kbd>
          move
          <Kbd>C</Kbd>
          confirm
          <Kbd>D</Kbd>
          dismiss
        </div>
      }
    >
      <section
        ref={rootRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        className="outline-none"
        data-testid="review-inbox"
      >
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <Input
            aria-label="Minimum score"
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            placeholder="min score"
            className="w-24"
          />
          <Input
            aria-label="Domain filter"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            placeholder="domain"
            className="w-40"
          />
          <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-muted">
            <input
              type="checkbox"
              checked={keepBlur}
              onChange={(e) => void toggleKeepBlur(e.target.checked)}
            />
            keep blur on
          </label>
        </div>

        {error && <p className="px-4 pt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        {/* Bulk dismiss by domain */}
        <div className="flex flex-wrap items-center gap-2 bg-surface-muted/60 px-4 py-2 text-sm">
          <span className="text-fg-muted">Bulk dismiss:</span>
          <Input
            aria-label="Bulk dismiss domain"
            value={bulkDomain}
            onChange={(e) => {
              setBulkDomain(e.target.value);
              setBulkPreview(null);
            }}
            placeholder="domain"
            className="w-40"
          />
          <Select
            aria-label="Bulk dismiss reason"
            value={bulkReason}
            onChange={(e) => setBulkReason(e.target.value as DismissReason)}
          >
            {DISMISS_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
          <Button variant="secondary" size="sm" onClick={() => void previewBulk()}>
            Preview
          </Button>
          {bulkPreview !== null && (
            <Button variant="danger" size="sm" onClick={() => void applyBulk()}>
              Dismiss {bulkPreview}
            </Button>
          )}
        </div>

        {rows.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="Inbox clear"
              description="No candidates waiting. New discovery matches land here for review."
            />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((it, idx) => (
              <li
                key={it.id}
                className={`flex gap-3 px-4 py-3 ${
                  idx === selected ? "bg-primary/5 ring-1 ring-inset ring-primary/30" : ""
                }`}
                onClick={() => setSelected(idx)}
              >
                <div className="flex gap-1">
                  <Thumb workspaceId={workspaceId} candidateId={it.id} kind="asset" blur={false} />
                  <Thumb workspaceId={workspaceId} candidateId={it.id} kind="found" blur={keepBlur} />
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{it.subject_name}</span>
                    <span className="text-xs text-fg-muted">{it.provider}</span>
                  </div>
                  <ScoreBadge item={it} />
                  <a
                    href={it.page_url ?? it.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block max-w-md truncate text-xs text-primary hover:underline"
                  >
                    {it.page_url ?? it.source_url}
                  </a>
                </div>
                <div className="w-56 space-y-1.5 text-sm">
                  {it.supported_claims.length > 0 ? (
                    <Select
                      aria-label="Claim type"
                      value={claimFor(it)}
                      onChange={(e) => setClaimByItem((m) => ({ ...m, [it.id]: e.target.value }))}
                    >
                      {it.supported_claims.map((c) => (
                        <option key={c} value={c}>
                          {c}
                          {c === it.suggested_claim ? " (suggested)" : ""}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <span className="text-xs text-amber-700 dark:text-amber-400">
                      claim: not supported
                    </span>
                  )}
                  <div className="flex gap-1">
                    <Button
                      variant="primary"
                      size="sm"
                      className="flex-1 bg-emerald-600 hover:bg-emerald-700"
                      disabled={it.supported_claims.length === 0 || busy}
                      onClick={() => void doConfirm(it)}
                    >
                      Confirm
                    </Button>
                    <Select
                      aria-label="Dismiss reason"
                      value={reasonFor(it)}
                      onChange={(e) =>
                        setReasonByItem((m) => ({ ...m, [it.id]: e.target.value as DismissReason }))
                      }
                    >
                      {DISMISS_REASONS.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </Select>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void doDismiss(it)}
                    >
                      Dismiss
                    </Button>
                  </div>
                  {isAdmin && (
                    <button
                      className="text-[11px] text-fg-muted hover:text-fg"
                      onClick={() => {
                        setReopenId(it.id);
                        setReopenNote("");
                      }}
                    >
                      reopen…
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Modal
        open={reopenId !== null}
        onClose={() => setReopenId(null)}
        title="Reopen candidate"
        footer={
          <>
            <Button variant="secondary" onClick={() => setReopenId(null)}>
              Cancel
            </Button>
            <Button disabled={!reopenNote.trim()} onClick={() => void submitReopen()}>
              Reopen
            </Button>
          </>
        }
      >
        <Textarea
          label="Reason for reopening"
          value={reopenNote}
          onChange={(e) => setReopenNote(e.target.value)}
          autoFocus
        />
      </Modal>
    </Card>
  );
}
