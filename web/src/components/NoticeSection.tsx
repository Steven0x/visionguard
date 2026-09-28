import { useCallback, useEffect, useState } from "react";
import {
  type NoticeDetail,
  type NoticePacket,
  approveNotice,
  createNoticeDraft,
  editNoticeDraft,
  getNotice,
  getNoticePacket,
  recordHandSubmission,
  retrySendNotice,
  sendNotice,
  withdrawNotice,
} from "../api";
import { useToken } from "../useToken";

// The concierge files through these platforms (see ops/RUNBOOK_day1.md).
const PLATFORMS = [
  "generic_host",
  "instagram",
  "facebook",
  "tiktok",
  "x",
  "google_search",
  "amazon",
];

export function NoticeSection({
  workspaceId,
  caseId,
}: {
  workspaceId: number;
  caseId: number;
}) {
  const getToken = useToken();
  const [detail, setDetail] = useState<NoticeDetail | null>(null);
  const [packet, setPacket] = useState<NoticePacket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [platform, setPlatform] = useState(PLATFORMS[0]);
  const [fairUse, setFairUse] = useState(false);

  const reload = useCallback(async () => {
    try {
      setDetail(await getNotice(await getToken(), workspaceId, caseId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, caseId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Disable buttons while a request is in flight (mirrors the case actions pattern).
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const notice = detail?.notice ?? null;

  return (
    <section className="space-y-2" data-testid="notice-section">
      <h4 className="font-medium">Notice</h4>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!notice && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500">Draft a notice for:</span>
          <select
            className="border p-1"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <button
            disabled={busy}
            className="rounded bg-blue-700 px-2 py-1 text-white disabled:opacity-50"
            onClick={() =>
              act(async () => createNoticeDraft(await getToken(), workspaceId, caseId, platform))
            }
          >
            Create draft
          </button>
        </div>
      )}

      {notice && detail && (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">
              {notice.platform} · {notice.method} · {notice.status}
            </span>
            {notice.approved_at ? (
              <span className="text-xs text-green-700">approved ✓</span>
            ) : (
              <span className="text-xs text-gray-500">not yet approved</span>
            )}
            {notice.sealed_capture_id && (
              <span className="text-xs text-gray-500">sealed #{notice.sealed_capture_id}</span>
            )}
          </div>

          {/* Why the notice can't go out yet — makes the "unapproved until counsel" gate visible. */}
          {notice.status === "draft" && detail.blockers.length > 0 && (
            <ul className="rounded bg-amber-50 p-2 text-xs text-amber-800">
              {detail.blockers.map((b) => (
                <li key={b}>• {b}</li>
              ))}
            </ul>
          )}

          {notice.status === "draft" && (
            <DraftEditor
              detail={detail}
              busy={busy}
              onSave={(subject, body) =>
                act(async () =>
                  editNoticeDraft(await getToken(), workspaceId, caseId, subject, body),
                )
              }
            />
          )}

          {notice.status === "draft" && (
            <div className="flex flex-wrap items-center gap-2">
              {notice.claim_type === "copyright" && (
                <label className="flex items-center gap-1 text-xs text-gray-600">
                  <input
                    type="checkbox"
                    checked={fairUse}
                    onChange={(e) => setFairUse(e.target.checked)}
                  />
                  I considered fair use
                </label>
              )}
              <button
                disabled={busy}
                className="rounded bg-gray-800 px-2 py-1 text-xs text-white disabled:opacity-50"
                onClick={() =>
                  act(async () => approveNotice(await getToken(), workspaceId, caseId, fairUse))
                }
              >
                {notice.approved_at ? "Re-approve" : "Approve"}
              </button>
              {notice.method === "email" && (
                <button
                  disabled={busy || !detail.can_send}
                  title={detail.can_send ? "" : detail.blockers.join("; ")}
                  className="rounded bg-red-700 px-2 py-1 text-xs text-white disabled:opacity-50"
                  onClick={() => act(async () => sendNotice(await getToken(), workspaceId, caseId))}
                >
                  Send
                </button>
              )}
              {notice.method !== "email" && (
                <>
                  <button
                    disabled={busy}
                    className="rounded bg-gray-700 px-2 py-1 text-xs text-white disabled:opacity-50"
                    onClick={() =>
                      act(async () => {
                        setPacket(await getNoticePacket(await getToken(), workspaceId, caseId));
                      })
                    }
                  >
                    View packet
                  </button>
                  <HandSubmission
                    busy={busy || !detail.can_send}
                    disabledReason={detail.can_send ? "" : detail.blockers.join("; ")}
                    onSubmit={(ticket, file) =>
                      act(async () =>
                        recordHandSubmission(await getToken(), workspaceId, caseId, ticket, file),
                      )
                    }
                  />
                </>
              )}
            </div>
          )}

          {notice.status === "delivery_failed" && (
            <div className="flex items-center gap-2 rounded bg-red-50 p-2 text-xs text-red-800">
              <span>Delivery failed — the case is Filed but the email did not go out.</span>
              <button
                disabled={busy}
                className="rounded bg-red-700 px-2 py-1 text-white disabled:opacity-50"
                onClick={() => act(async () => retrySendNotice(await getToken(), workspaceId, caseId))}
              >
                Retry send
              </button>
            </div>
          )}

          {notice.status === "sent" && (
            <WithdrawForm
              busy={busy}
              onWithdraw={(note) =>
                act(async () => withdrawNotice(await getToken(), workspaceId, caseId, note))
              }
            />
          )}

          {packet && notice.method !== "email" && (
            <div className="rounded border border-gray-200 p-2 text-xs">
              <div className="font-medium">Copy-ready packet — submit at:</div>
              <a href={packet.destination} target="_blank" rel="noopener noreferrer" className="text-blue-700">
                {packet.destination}
              </a>
              <pre className="mt-1 whitespace-pre-wrap">{`${packet.subject}\n\n${packet.body}`}</pre>
              <div className="mt-1 text-gray-500">{packet.instructions}</div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function DraftEditor({
  detail,
  busy,
  onSave,
}: {
  detail: NoticeDetail;
  busy: boolean;
  onSave: (subject: string, body: string) => void;
}) {
  const latest = detail.versions[detail.versions.length - 1];
  const [subject, setSubject] = useState(latest?.subject ?? "");
  const [body, setBody] = useState(latest?.body ?? "");
  // Re-seed the editor when a new version arrives (e.g. after a save).
  useEffect(() => {
    setSubject(latest?.subject ?? "");
    setBody(latest?.body ?? "");
  }, [latest?.version]);

  return (
    <div className="space-y-1">
      <input
        className="w-full border p-1"
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        placeholder="subject"
      />
      <textarea
        className="h-40 w-full border p-1 font-mono text-xs"
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="flex items-center gap-2">
        <button
          disabled={busy}
          className="rounded bg-blue-700 px-2 py-1 text-xs text-white disabled:opacity-50"
          onClick={() => onSave(subject, body)}
        >
          Save version
        </button>
        <span className="text-xs text-gray-400">v{detail.notice?.current_version}</span>
      </div>
    </div>
  );
}

function HandSubmission({
  busy,
  disabledReason,
  onSubmit,
}: {
  busy: boolean;
  disabledReason: string;
  onSubmit: (ticket: string, file: File) => void;
}) {
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const ticket = (form.elements.namedItem("ticket") as HTMLInputElement).value;
        const file = (form.elements.namedItem("file") as HTMLInputElement).files?.[0];
        if (ticket.trim() && file) {
          onSubmit(ticket, file);
          form.reset();
        }
      }}
    >
      <input name="ticket" placeholder="ticket #" required className="border p-1 text-xs" />
      <input name="file" type="file" accept="image/png,image/jpeg,image/webp" required />
      <button
        disabled={busy}
        title={disabledReason}
        className="rounded bg-red-700 px-2 py-1 text-xs text-white disabled:opacity-50"
      >
        Record submission
      </button>
    </form>
  );
}

function WithdrawForm({
  busy,
  onWithdraw,
}: {
  busy: boolean;
  onWithdraw: (note: string) => void;
}) {
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const input = e.currentTarget.elements.namedItem("note") as HTMLInputElement;
        if (input.value.trim()) {
          onWithdraw(input.value);
          e.currentTarget.reset();
        }
      }}
    >
      <input name="note" placeholder="retraction note (required)" required className="border p-1 text-xs" />
      <button
        disabled={busy}
        className="rounded bg-gray-700 px-2 py-1 text-xs text-white disabled:opacity-50"
      >
        Withdraw
      </button>
    </form>
  );
}
