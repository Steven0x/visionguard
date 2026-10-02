import { useCallback, useEffect, useState } from "react";
import {
  type ReportRow,
  type Subject,
  fetchReportBlob,
  generateReport,
  listReports,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { Button, Card, EmptyState, Select, Table, TD, TH, THead, TR } from "./ui";

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
      setError(errorText(e));
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
      setError(errorText(e));
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
      setError(errorText(e));
    }
  };

  return (
    <div className="space-y-4" data-testid="reports-section">
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <Card title="Generate report">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <Select
            label="Scope"
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
          >
            <option value="">Whole workspace</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.legal_name}
              </option>
            ))}
          </Select>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-fg-muted" htmlFor="report-from">
              From
            </label>
            <input
              id="report-from"
              type="date"
              className="rounded-md border-0 bg-surface px-2.5 py-1.5 text-sm text-fg shadow-sm ring-1 ring-inset ring-line focus:ring-2 focus:ring-focus"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-fg-muted" htmlFor="report-to">
              To
            </label>
            <input
              id="report-to"
              type="date"
              className="rounded-md border-0 bg-surface px-2.5 py-1.5 text-sm text-fg shadow-sm ring-1 ring-inset ring-line focus:ring-2 focus:ring-focus"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            <input type="checkbox" checked={thumbs} onChange={(e) => setThumbs(e.target.checked)} />
            thumbnails
          </label>
          <Button onClick={() => void onGenerate()} disabled={busy}>
            {busy ? "Generating…" : "Generate"}
          </Button>
        </div>
      </Card>

      <Card title="Reports" bodyClassName={reports.length ? "p-0" : "p-4"}>
        {reports.length === 0 ? (
          <EmptyState title="No reports yet" description="Generate one above to share with the agency." />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>#</TH>
                <TH>Scope</TH>
                <TH>Period</TH>
                <TH>Generated</TH>
                <TH />
              </tr>
            </THead>
            <tbody>
              {reports.map((r) => (
                <TR key={r.id}>
                  <TD className="font-mono text-xs">{r.id}</TD>
                  <TD>{r.subject_id == null ? "workspace" : `subject ${r.subject_id}`}</TD>
                  <TD>
                    {r.period_start} → {r.period_end}
                  </TD>
                  <TD className="text-fg-muted">{r.as_of.slice(0, 10)}</TD>
                  <TD>
                    <Button variant="ghost" size="sm" onClick={() => void download(r, "pdf")}>
                      PDF
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void download(r, "json")}>
                      inputs
                    </Button>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
