import type { DiscoveryRun } from "../api";
import { Badge, type Tone } from "./ui";

const TONE: Record<DiscoveryRun["status"], Tone> = {
  running: "blue",
  completed: "green",
  partial: "amber",
  blocked: "red",
  failed: "red",
};

export function RunStatusBadge({ status }: { status: DiscoveryRun["status"] }) {
  return (
    <Badge tone={TONE[status]} data-testid="run-status">
      {status}
    </Badge>
  );
}
