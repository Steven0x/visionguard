import type { EvidenceCapture } from "../api";

const STATUS: Record<EvidenceCapture["status"], string> = {
  pending: "bg-blue-100 text-blue-700",
  sealed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  blocked: "bg-red-100 text-red-700",
};

/** Pure: a capture's status + timestamp state (sealed-but-untimestamped is worth flagging). */
export function EvidenceStatusBadge({
  capture,
}: {
  capture: Pick<EvidenceCapture, "status" | "timestamp_status">;
}) {
  return (
    <span className="inline-flex items-center gap-1" data-testid="evidence-status">
      <span className={`rounded px-2 py-0.5 text-xs ${STATUS[capture.status]}`}>
        {capture.status}
      </span>
      {capture.status === "sealed" && capture.timestamp_status === "untimestamped" && (
        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800" data-testid="untimestamped">
          untimestamped
        </span>
      )}
      {capture.status === "sealed" && capture.timestamp_status === "ok" && (
        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
          timestamped
        </span>
      )}
    </span>
  );
}
