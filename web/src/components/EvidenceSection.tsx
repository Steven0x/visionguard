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
import { useToken } from "../useToken";
import { EvidenceStatusBadge } from "./EvidenceStatusBadge";

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

  const reload = useCallback(async () => {
    try {
      setCaptures(await listEvidence(await getToken(), workspaceId, caseId));
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

  const doVerify = async (eid: number) => {
    setError(null);
    try {
      const r = await verifyEvidence(await getToken(), workspaceId, caseId, eid, "manual review");
      setVerifyMsg((m) => ({ ...m, [eid]: r.ok ? "verified ✓" : "VERIFICATION FAILED" }));
    } catch (e) {
      setError(String(e));
    }
  };

  const openArtifact = async (eid: number, name: string) => {
    const { url } = await evidenceArtifactUrl(
      await getToken(), workspaceId, caseId, eid, name, "review",
    );
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const openPack = () => {
    const reason = window.prompt("Reason for exporting the evidence pack (logged):");
    if (!reason) return;
    const includeSensitive = window.confirm(
      "Include sensitive screenshots un-blurred? (logged). Cancel = blurred.",
    );
    window.open(
      evidencePackUrl(workspaceId, caseId, reason, includeSensitive), "_blank",
      "noopener,noreferrer",
    );
  };

  return (
    <section className="space-y-2" data-testid="evidence-section">
      <div className="flex items-center gap-3">
        <h4 className="font-medium">Evidence ({captures.length})</h4>
        <button
          className="rounded bg-gray-800 px-2 py-1 text-xs text-white"
          onClick={() => act(async () => recapture(await getToken(), workspaceId, caseId))}
        >
          Recapture
        </button>
        {isAdmin && (
          <button className="rounded bg-gray-700 px-2 py-1 text-xs text-white" onClick={openPack}>
            Download pack (PDF)
          </button>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <form
        className="flex items-center gap-2 text-sm"
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
        <span className="text-gray-500">Manual upload:</span>
        <input name="file" type="file" accept="image/png,image/jpeg,image/webp" required />
        <input name="note" placeholder="attestation (required)" required className="border p-1" />
        <button className="rounded bg-blue-700 px-2 py-1 text-white">Upload</button>
      </form>

      <ul className="space-y-1 text-xs">
        {captures.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2 border-t border-gray-100 py-1">
            <EvidenceStatusBadge capture={c} />
            <span>{c.kind}</span>
            {c.error && <span className="text-red-600">{c.error}</span>}
            <span className="text-gray-400">{(c.capture_finished_at ?? c.created_at).slice(0, 19)}</span>
            {c.status === "sealed" && (
              <>
                <button className="text-blue-700" onClick={() => void openArtifact(c.id, "screenshot.png")}>
                  screenshot
                </button>
                <button className="text-blue-700" onClick={() => void openArtifact(c.id, "manifest.json")}>
                  manifest
                </button>
                <button className="text-blue-700" onClick={() => void doVerify(c.id)}>
                  verify
                </button>
                {verifyMsg[c.id] && (
                  <span className={verifyMsg[c.id].includes("FAIL") ? "text-red-600" : "text-green-700"}>
                    {verifyMsg[c.id]}
                  </span>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
