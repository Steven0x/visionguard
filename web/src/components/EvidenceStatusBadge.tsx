import type { EvidenceCapture } from "../api";
import { Badge, type Tone } from "./ui";

const TONE: Record<EvidenceCapture["status"], Tone> = {
  pending: "blue",
  sealed: "green",
  failed: "red",
  blocked: "red",
};

/** Pure: a capture's status + timestamp state (sealed-but-untimestamped is worth flagging). */
export function EvidenceStatusBadge({
  capture,
}: {
  capture: Pick<EvidenceCapture, "status" | "timestamp_status">;
}) {
  return (
    <span className="inline-flex items-center gap-1" data-testid="evidence-status">
      <Badge tone={TONE[capture.status]}>{capture.status}</Badge>
      {capture.status === "sealed" && capture.timestamp_status === "untimestamped" && (
        <Badge tone="amber" title="untimestamped">
          <span data-testid="untimestamped">untimestamped</span>
        </Badge>
      )}
      {capture.status === "sealed" && capture.timestamp_status === "ok" && (
        <Badge tone="gray">timestamped</Badge>
      )}
    </span>
  );
}
