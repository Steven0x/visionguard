import type { AssetStatus } from "../api";

const STYLES: Record<AssetStatus, string> = {
  pending: "bg-gray-100 text-gray-700",
  processing: "bg-blue-100 text-blue-700",
  ready: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

export function AssetStatusBadge({ status }: { status: AssetStatus }) {
  return (
    <span
      data-testid="asset-status"
      className={`rounded px-2 py-0.5 text-xs ${STYLES[status]}`}
    >
      {status}
    </span>
  );
}
