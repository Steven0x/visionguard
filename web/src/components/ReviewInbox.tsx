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
import { useToken } from "../useToken";
import { ScoreBadge } from "./ScoreBadge";

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
      <div className="flex h-24 w-24 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
        {kind === "asset" ? "no match" : "link"}
      </div>
    );
  }
  const hidden = kind === "found" && blur && !revealed;
  return (
    <button
      type="button"
      className="relative h-24 w-24 overflow-hidden rounded"
      title={hidden ? "click to reveal" : undefined}
      onClick={() => kind === "found" && setRevealed((v) => !v)}
    >
      <img
        src={url}
        alt={kind}
        className={`h-24 w-24 object-cover ${hidden ? "blur-lg" : ""}`}
        data-testid={`thumb-${kind}`}
      />
      {hidden && (
        <span className="absolute inset-0 flex items-center justify-center text-[10px] text-white">
          click to reveal
        </span>
      )}
    </button>
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
  const [items, setItems] = useState<InboxItem[]>([]);
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
      setError(String(e));
    }
  }, [getToken, workspaceId, minScore, domainFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const claimFor = (it: InboxItem) =>
    claimByItem[it.id] ?? it.suggested_claim ?? it.supported_claims[0] ?? "";
  const reasonFor = (it: InboxItem) => reasonByItem[it.id] ?? "not_a_match";

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const doConfirm = async (it: InboxItem) => {
    const claim = claimFor(it);
    if (!claim) {
      setError("no supported claim for this subject — add rights/consent first");
      return;
    }
    await act(async () => confirmCandidate(await getToken(), workspaceId, it.id, claim));
  };
  const doDismiss = async (it: InboxItem) =>
    act(async () => dismissCandidate(await getToken(), workspaceId, it.id, reasonFor(it)));
  const doReopen = async (it: InboxItem) => {
    const note = window.prompt("Reason for reopening this candidate?");
    if (!note) return;
    await act(async () => reopenCandidate(await getToken(), workspaceId, it.id, note));
  };

  // Keyboard: J/K move, C confirm, D dismiss.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (items.length === 0) return;
    const it = items[selected];
    if (e.key === "j" || e.key === "J") setSelected((s) => Math.min(items.length - 1, s + 1));
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
      setError(String(e));
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

  return (
    <section
      ref={rootRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="space-y-3 rounded border border-gray-200 p-3 outline-none"
      data-testid="review-inbox"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-medium">Review inbox ({items.length})</h3>
        <input
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
          placeholder="min score"
          className="w-24 border p-1 text-sm"
        />
        <input
          value={domainFilter}
          onChange={(e) => setDomainFilter(e.target.value)}
          placeholder="domain"
          className="w-40 border p-1 text-sm"
        />
        <label className="ml-auto text-xs text-gray-600">
          <input
            type="checkbox"
            checked={keepBlur}
            onChange={(e) => void toggleKeepBlur(e.target.checked)}
          />{" "}
          keep blur on
        </label>
      </div>
      <p className="text-[11px] text-gray-400">
        Keys: J/K move · C confirm · D dismiss. Found content is blurred — click to reveal.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Bulk dismiss by domain */}
      <div className="flex flex-wrap items-center gap-2 rounded bg-gray-50 p-2 text-sm">
        <span className="text-gray-500">Bulk dismiss:</span>
        <input
          value={bulkDomain}
          onChange={(e) => {
            setBulkDomain(e.target.value);
            setBulkPreview(null);
          }}
          placeholder="domain"
          className="w-40 border p-1"
        />
        <select
          value={bulkReason}
          onChange={(e) => setBulkReason(e.target.value as DismissReason)}
          className="border p-1"
        >
          {DISMISS_REASONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button className="rounded bg-gray-700 px-2 py-1 text-white" onClick={() => void previewBulk()}>
          Preview
        </button>
        {bulkPreview !== null && (
          <button
            className="rounded bg-red-700 px-2 py-1 text-white"
            onClick={() => void applyBulk()}
          >
            Dismiss {bulkPreview}
          </button>
        )}
      </div>

      <ul className="space-y-2">
        {items.map((it, idx) => (
          <li
            key={it.id}
            className={`flex gap-3 rounded border p-2 ${
              idx === selected ? "border-blue-500 bg-blue-50" : "border-gray-100"
            }`}
            onClick={() => setSelected(idx)}
          >
            <div className="flex gap-1">
              <Thumb workspaceId={workspaceId} candidateId={it.id} kind="asset" blur={false} />
              <Thumb workspaceId={workspaceId} candidateId={it.id} kind="found" blur={keepBlur} />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{it.subject_name}</span>
                <span className="text-xs text-gray-400">{it.provider}</span>
              </div>
              <ScoreBadge item={it} />
              <a
                href={it.page_url ?? it.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="block max-w-md truncate text-xs text-blue-700"
              >
                {it.page_url ?? it.source_url}
              </a>
            </div>
            <div className="w-56 space-y-1 text-sm">
              {it.supported_claims.length > 0 ? (
                <select
                  value={claimFor(it)}
                  onChange={(e) =>
                    setClaimByItem((m) => ({ ...m, [it.id]: e.target.value }))
                  }
                  className="w-full border p-1"
                >
                  {it.supported_claims.map((c) => (
                    <option key={c} value={c}>
                      {c}
                      {c === it.suggested_claim ? " (suggested)" : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-xs text-amber-700">claim: not supported</span>
              )}
              <div className="flex gap-1">
                <button
                  className="flex-1 rounded bg-green-700 px-2 py-1 text-white disabled:opacity-40"
                  disabled={it.supported_claims.length === 0}
                  onClick={() => void doConfirm(it)}
                >
                  Confirm
                </button>
                <select
                  value={reasonFor(it)}
                  onChange={(e) =>
                    setReasonByItem((m) => ({ ...m, [it.id]: e.target.value as DismissReason }))
                  }
                  className="border p-1 text-xs"
                >
                  {DISMISS_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  className="rounded bg-gray-700 px-2 py-1 text-white"
                  onClick={() => void doDismiss(it)}
                >
                  Dismiss
                </button>
              </div>
              {isAdmin && (
                <button
                  className="text-[11px] text-gray-500"
                  onClick={() => void doReopen(it)}
                >
                  reopen…
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {items.length === 0 && <p className="text-sm text-gray-400">Inbox clear.</p>}
    </section>
  );
}
