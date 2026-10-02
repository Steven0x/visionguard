import { useCallback, useEffect, useState } from "react";
import {
  type EvidenceCapture,
  evidenceArtifactUrl,
  evidencePackUrl,
  listEvidence,
  recapture,
  uploadEvidence,
  verifyEvidence,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { EvidenceStatusBadge } from "./EvidenceStatusBadge";
import { Button, Card, Input, Modal, Textarea } from "./ui";

export function EvidenceSection({
  workspaceId,
  caseId,
  isAdmin,
}: {
  workspaceId: number;
  caseId: number;
  isAdmin: boolean;
}) {
  const getToken = useToken();
  const [captures, setCaptures] = useState<EvidenceCapture[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [verifyMsg, setVerifyMsg] = useState<Record<number, string>>({});
  const [packOpen, setPackOpen] = useState(false);
  const [packReason, setPackReason] = useState("");
  const [packSensitive, setPackSensitive] = useState(false);

  const reload = useCallback(async () => {
    try {
      setCaptures(await listEvidence(await getToken(), workspaceId, caseId));
    } catch (e) {
      setError(errorText(e));
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
      setError(errorText(e));
    }
  };

  const doVerify = async (eid: number) => {
    setError(null);
    try {
      const r = await verifyEvidence(await getToken(), workspaceId, caseId, eid, "manual review");
      setVerifyMsg((m) => ({ ...m, [eid]: r.ok ? "verified ✓" : "VERIFICATION FAILED" }));
    } catch (e) {
      setError(errorText(e));
    }
  };

  const openArtifact = async (eid: number, name: string) => {
    const { url } = await evidenceArtifactUrl(
      await getToken(),
      workspaceId,
      caseId,
      eid,
      name,
      "review",
    );
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const exportPack = () => {
    if (!packReason.trim()) return;
    window.open(
      evidencePackUrl(workspaceId, caseId, packReason.trim(), packSensitive),
      "_blank",
      "noopener,noreferrer",
    );
    setPackOpen(false);
    setPackReason("");
    setPackSensitive(false);
  };

  return (
    <Card
      data-testid="evidence-section"
      title={`Evidence (${captures.length})`}
      actions={
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => act(async () => recapture(await getToken(), workspaceId, caseId))}
          >
            Recapture
          </Button>
          {isAdmin && (
            <Button variant="secondary" size="sm" onClick={() => setPackOpen(true)}>
              Download pack (PDF)
            </Button>
          )}
        </>
      }
    >
      {error && <p className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>}

      <form
        className="mb-3 flex flex-wrap items-center gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const fileInput = form.elements.namedItem("file") as HTMLInputElement;
          const noteInput = form.elements.namedItem("note") as HTMLInputElement;
          const file = fileInput.files?.[0];
          if (file && noteInput.value.trim()) {
            void act(async () =>
              uploadEvidence(await getToken(), workspaceId, caseId, file, noteInput.value),
            );
            form.reset();
          }
        }}
      >
        <span className="text-fg-muted">Manual upload:</span>
        <input
          name="file"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          required
          aria-label="Evidence file"
          className="text-sm text-fg-muted file:mr-2 file:rounded-md file:border-0 file:bg-surface-muted file:px-2 file:py-1 file:text-sm file:font-medium file:text-fg"
        />
        <Input name="note" aria-label="Attestation" placeholder="attestation (required)" required />
        <Button type="submit">Upload</Button>
      </form>

      <ul className="space-y-1 text-xs">
        {captures.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 first:border-0">
            <EvidenceStatusBadge capture={c} />
            <span>{c.kind}</span>
            {c.error && <span className="text-red-600 dark:text-red-400">{c.error}</span>}
            <span className="text-fg-muted">
              {(c.capture_finished_at ?? c.created_at).slice(0, 19)}
            </span>
            {c.status === "sealed" && (
              <>
                <Button variant="ghost" size="sm" onClick={() => void openArtifact(c.id, "screenshot.png")}>
                  screenshot
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void openArtifact(c.id, "manifest.json")}>
                  manifest
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void doVerify(c.id)}>
                  verify
                </Button>
                {verifyMsg[c.id] && (
                  <span
                    className={
                      verifyMsg[c.id].includes("FAIL")
                        ? "text-red-600 dark:text-red-400"
                        : "text-emerald-700 dark:text-emerald-400"
                    }
                  >
                    {verifyMsg[c.id]}
                  </span>
                )}
              </>
            )}
          </li>
        ))}
      </ul>

      <Modal
        open={packOpen}
        onClose={() => setPackOpen(false)}
        title="Export evidence pack"
        footer={
          <>
            <Button variant="secondary" onClick={() => setPackOpen(false)}>
              Cancel
            </Button>
            <Button disabled={!packReason.trim()} onClick={exportPack}>
              Export PDF
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Textarea
            label="Reason for export (logged)"
            value={packReason}
            onChange={(e) => setPackReason(e.target.value)}
            autoFocus
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={packSensitive}
              onChange={(e) => setPackSensitive(e.target.checked)}
            />
            Include sensitive screenshots un-blurred (logged)
          </label>
        </div>
      </Modal>
    </Card>
  );
}
