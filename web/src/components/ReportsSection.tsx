import { useCallback, useEffect, useState } from "react";
import {
  type ReportRow,
  type Subject,
  fetchReportBlob,
  generateReport,
  listReports,
} from "../api";
import { useToken } from "../useToken";

/** Agency reports: staff pick a scope + date range, generate a PDF, and download prior reports.
 * Nothing is sent automatically — generation and download are audited server-side. */
export function ReportsSection({
  workspaceId,
  subjects,
}: {
  workspaceId: number;
  subjects: Subject[];
}) {
  const getToken = useToken();
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 86400_000).toISOString().slice(0, 10);
  const [subjectId, setSubjectId] = useState<string>(""); // "" = whole workspace
  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const [thumbs, setThumbs] = useState(false);

  const reload = useCallback(async () => {
    setError(null);
    try {
      setReports(await listReports(await getToken(), workspaceId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onGenerate = async () => {
    setBusy(true);
    setError(null);
    try {
      await generateReport(await getToken(), workspaceId, {
        subject_id: subjectId ? Number(subjectId) : null,
        start,
        end,
        include_thumbnails: thumbs,
      });
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const download = async (report: ReportRow, which: "pdf" | "json") => {
    try {
      const blob = await fetchReportBlob(await getToken(), workspaceId, report.id, which);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report-${report.id}.${which === "pdf" ? "pdf" : "inputs.json"}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section
      className="space-y-3 rounded border border-gray-200 p-3"
      data-testid="reports-section"
    >
      <h3 className="font-medium">Agency reports</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col">
          <span className="text-gray-500">Scope</span>
          <select
            className="rounded border border-gray-300 p-1"
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
          >
            <option value="">Whole workspace</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.legal_name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          <span className="text-gray-500">From</span>
          <input
            type="date"
            className="rounded border border-gray-300 p-1"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label className="flex flex-col">
          <span className="text-gray-500">To</span>
          <input
            type="date"
            className="rounded border border-gray-300 p-1"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={thumbs}
            onChange={(e) => setThumbs(e.target.checked)}
          />
          thumbnails
        </label>
        <button
          className="rounded bg-blue-700 px-3 py-1 text-white disabled:opacity-50"
          onClick={() => void onGenerate()}
          disabled={busy}
        >
          {busy ? "Generating…" : "Generate"}
        </button>
      </div>

      {reports.length === 0 ? (
        <p className="text-sm text-gray-400">No reports generated yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="p-1">#</th>
              <th className="p-1">Scope</th>
              <th className="p-1">Period</th>
              <th className="p-1">Generated</th>
              <th className="p-1" />
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id} className="border-t border-gray-100">
                <td className="p-1 font-mono">{r.id}</td>
                <td className="p-1">
                  {r.subject_id == null ? "workspace" : `subject ${r.subject_id}`}
                </td>
                <td className="p-1">
                  {r.period_start} → {r.period_end}
                </td>
                <td className="p-1 text-gray-600">{r.as_of.slice(0, 10)}</td>
                <td className="p-1">
                  <button
                    className="text-blue-700"
                    onClick={() => void download(r, "pdf")}
                  >
                    PDF
                  </button>
                  {" · "}
                  <button
                    className="text-blue-700"
                    onClick={() => void download(r, "json")}
                  >
                    inputs
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
