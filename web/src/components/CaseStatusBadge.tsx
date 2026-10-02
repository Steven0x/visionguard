import type { CaseRow } from "../api";
import { StatusBadge } from "./ui/StatusBadge";

/** Thin adapter kept for existing call sites. The status→color map now lives in one place:
 * ui/StatusBadge (STATUS_TONE). */
export function CaseStatusBadge({ row }: { row: Pick<CaseRow, "status" | "overdue"> }) {
  return <StatusBadge status={row.status} overdue={row.overdue} />;
}
