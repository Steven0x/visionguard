import type { PreviewRow } from "../api";

/** Pure render of a CSV import preview: one row per record, errors highlighted. */
export function ImportPreviewTable({ rows }: { rows: PreviewRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-gray-500">
          <th className="p-1">#</th>
          <th className="p-1">Legal name</th>
          <th className="p-1">Handles</th>
          <th className="p-1">Residence</th>
          <th className="p-1">Errors</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const values = row.values as Record<string, unknown>;
          const handles = (values.handles as string[] | undefined) ?? [];
          return (
            <tr
              key={row.row_no}
              className={row.errors.length ? "bg-red-50" : ""}
              data-testid={`row-${row.row_no}`}
            >
              <td className="p-1">{row.row_no}</td>
              <td className="p-1">{String(values.legal_name ?? "")}</td>
              <td className="p-1">{handles.join(", ")}</td>
              <td className="p-1">{String(values.residence_state ?? "")}</td>
              <td className="p-1 text-red-600">{row.errors.join("; ")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
