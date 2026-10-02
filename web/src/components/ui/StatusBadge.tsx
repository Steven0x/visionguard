import type { CaseStatus } from "../../api";
import { Badge, type Tone } from "./Badge";

/** The ONE case-status → color mapping. Used everywhere a case status appears: staff inbox,
 * cases list, case view, the agency portal, and reports. Change a status color here and it
 * changes everywhere. */
export const STATUS_TONE: Record<CaseStatus, Tone> = {
  discovered: "gray",
  confirmed: "blue",
  dismissed: "gray",
  filed: "indigo",
  removed: "green",
  countered: "amber",
  escalated: "orange",
  withdrawn: "gray",
  monitoring: "teal",
  recovered: "green",
  closed: "gray",
};

export interface StatusBadgeProps {
  status: CaseStatus;
  overdue?: boolean;
}

/** A case's status pill, plus an overdue marker when its follow-up timer has lapsed. */
export function StatusBadge({ status, overdue = false }: StatusBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1" data-testid="case-status">
      <Badge tone={STATUS_TONE[status]} className="capitalize">
        {status}
      </Badge>
      {overdue && (
        <span
          data-testid="overdue"
          className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-medium text-white"
        >
          overdue
        </span>
      )}
    </span>
  );
}
