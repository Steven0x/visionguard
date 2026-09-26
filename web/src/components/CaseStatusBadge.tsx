import type { CaseRow, CaseStatus } from "../api";

const STYLES: Record<CaseStatus, string> = {
  discovered: "bg-gray-100 text-gray-700",
  confirmed: "bg-blue-100 text-blue-700",
  dismissed: "bg-gray-100 text-gray-500",
  filed: "bg-indigo-100 text-indigo-700",
  removed: "bg-green-100 text-green-700",
  countered: "bg-amber-100 text-amber-800",
  escalated: "bg-orange-100 text-orange-800",
  withdrawn: "bg-gray-100 text-gray-500",
  monitoring: "bg-teal-100 text-teal-700",
  recovered: "bg-green-100 text-green-700",
  closed: "bg-gray-200 text-gray-600",
};

/** Pure: a case's status pill, with an overdue marker when the follow-up timer has lapsed. */
export function CaseStatusBadge({ row }: { row: Pick<CaseRow, "status" | "overdue"> }) {
  return (
    <span className="inline-flex items-center gap-1" data-testid="case-status">
      <span className={`rounded px-2 py-0.5 text-xs ${STYLES[row.status]}`}>{row.status}</span>
      {row.overdue && (
        <span className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] text-white" data-testid="overdue">
          overdue
        </span>
      )}
    </span>
  );
}
