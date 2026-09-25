import type { DiscoveryRun } from "../api";

const STYLES: Record<DiscoveryRun["status"], string> = {
  running: "bg-blue-100 text-blue-700",
  completed: "bg-green-100 text-green-700",
  partial: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-700",
  failed: "bg-red-100 text-red-700",
};

export function RunStatusBadge({ status }: { status: DiscoveryRun["status"] }) {
  return (
    <span data-testid="run-status" className={`rounded px-2 py-0.5 text-xs ${STYLES[status]}`}>
      {status}
    </span>
  );
}
