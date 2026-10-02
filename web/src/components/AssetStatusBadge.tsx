import type { AssetStatus } from "../api";
import { Badge, type Tone } from "./ui";

const TONE: Record<AssetStatus, Tone> = {
  pending: "gray",
  processing: "blue",
  ready: "green",
  failed: "red",
};

export function AssetStatusBadge({ status }: { status: AssetStatus }) {
  return (
    <Badge tone={TONE[status]} data-testid="asset-status">
      {status}
    </Badge>
  );
}
