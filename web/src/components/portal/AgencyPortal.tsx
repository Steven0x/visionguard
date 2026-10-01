import { useCallback, useEffect, useState } from "react";
import {
  answerPortalNeed,
  fetchPortalReportPdf,
  getPortalCase,
  getPortalContext,
  listPortalCases,
  listPortalNeeds,
  listPortalReports,
  listPortalSubjects,
  submitPortalTip,
  type PortalCase,
  type PortalCaseDetail,
  type PortalContext,
  type PortalNeed,
  type PortalReport,
  type PortalSubject,
} from "../../api";
import { useToken } from "../../useToken";

type Tab = "cases" | "subjects" | "needs" | "reports";

/** The agency customer portal: a read-mostly view of their own enforcement, plus two limited
 * writes (submit a URL tip, answer a "Needs from you" item). Staff components are never rendered
 * here — this tree is reached only when me.role === "agency". */
export function AgencyPortal() {
  const getToken = useToken();
  const [ctx, setCtx] = useState<PortalContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("cases");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const result = await getPortalContext(await getToken());
        if (active) setCtx(result);
      } catch (e) {
        if (active) setError(String(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!ctx) return <p className="text-gray-500">Loading…</p>;

  const tabs: [Tab, string][] = [
    ["cases", "Cases"],
    ["subjects", "Subjects"],
    ["needs", "Needs from you"],
    ["reports", "Reports"],
  ];
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        {ctx.workspace_name} — signed in as {ctx.email}
      </p>
      <nav className="flex gap-2 border-b border-gray-200">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-3 py-1 text-sm ${
              tab === key ? "border-b-2 border-blue-700 font-semibold" : "text-gray-500"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "cases" && <CasesTab />}
      {tab === "subjects" && <SubjectsTab />}
      {tab === "needs" && <NeedsTab />}
      {tab === "reports" && <ReportsTab />}
    </div>
  );
}

function useAsync<T>(load: (token: string) => Promise<T>) {
  const getToken = useToken();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Keyed on getToken (a stable Clerk reference), mirroring the staff components; `load` is
  // effectively stable per mount, so this won't reload-loop even for an inline loader.
  const reload = useCallback(async () => {
    try {
      setData(await load(await getToken()));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, reload };
}

function CasesTab() {
  const { data: cases, error } = useAsync(listPortalCases);
  const [open, setOpen] = useState<number | null>(null);
  if (error) return <p className="text-red-600">{error}</p>;
  if (!cases) return <p className="text-gray-500">Loading…</p>;
  if (open !== null) return <CaseDetail caseId={open} onBack={() => setOpen(null)} />;
  if (cases.length === 0) return <p className="text-gray-500">No cases yet.</p>;
  return (
    <ul className="divide-y divide-gray-100">
      {cases.map((c: PortalCase) => (
        <li key={c.id} className="flex items-center justify-between py-2">
          <div>
            <button className="text-blue-700" onClick={() => setOpen(c.id)}>
              Case #{c.id}
            </button>
            <span className="ml-2 text-sm text-gray-500">{c.claim_type}</span>
            {c.display_url && (
              <span className="ml-2 text-xs text-gray-400">{c.display_url}</span>
            )}
          </div>
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">{c.status}</span>
        </li>
      ))}
    </ul>
  );
}

function CaseDetail({ caseId, onBack }: { caseId: number; onBack: () => void }) {
  const { data, error } = useAsync<PortalCaseDetail>((t) => getPortalCase(t, caseId));
  if (error) return <p className="text-red-600">{error}</p>;
  if (!data) return <p className="text-gray-500">Loading…</p>;
  return (
    <div className="space-y-2">
      <button className="text-sm text-blue-700" onClick={onBack}>
        ← Back
      </button>
      <h2 className="text-lg font-semibold">
        Case #{data.case.id} — {data.case.status}
      </h2>
      <ol className="space-y-1 text-sm">
        {data.timeline.map((e, i) => (
          <li key={i} className="text-gray-600">
            {e.from_status ?? "—"} → {e.to_status ?? "—"}{" "}
            <span className="text-gray-400">{e.created_at.slice(0, 10)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function SubjectsTab() {
  const { data: subjects, error } = useAsync(listPortalSubjects);
  if (error) return <p className="text-red-600">{error}</p>;
  if (!subjects) return <p className="text-gray-500">Loading…</p>;
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-gray-100">
        {subjects.map((s: PortalSubject) => (
          <li key={s.id} className="py-2">
            <span className="font-medium">{s.legal_name}</span>{" "}
            <span className="text-xs text-gray-400">{s.status}</span>
          </li>
        ))}
      </ul>
      <TipForm subjects={subjects} />
    </div>
  );
}

function TipForm({ subjects }: { subjects: PortalSubject[] }) {
  const getToken = useToken();
  const [subjectId, setSubjectId] = useState<number | "">("");
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const submit = async () => {
    setMsg(null);
    try {
      const r = await submitPortalTip(await getToken(), Number(subjectId), url);
      setMsg(r.detail);
      setUrl("");
    } catch (e) {
      setMsg(String(e));
    }
  };
  return (
    <form
      className="space-y-2 rounded border border-gray-200 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <h3 className="text-sm font-semibold">Submit a URL tip</h3>
      <select
        className="block w-64 border p-1"
        value={subjectId}
        onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : "")}
      >
        <option value="">Choose a subject…</option>
        {subjects.map((s) => (
          <option key={s.id} value={s.id}>
            {s.legal_name}
          </option>
        ))}
      </select>
      <input
        className="block w-full border p-1"
        placeholder="https://…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <button
        type="submit"
        disabled={!subjectId || !url}
        className="rounded bg-blue-700 px-2 py-1 text-white disabled:opacity-50"
      >
        Send tip
      </button>
      {msg && <p className="text-xs text-gray-600">{msg}</p>}
    </form>
  );
}

function NeedsTab() {
  const { data: needs, error, reload } = useAsync(listPortalNeeds);
  if (error) return <p className="text-red-600">{error}</p>;
  if (!needs) return <p className="text-gray-500">Loading…</p>;
  if (needs.length === 0)
    return <p className="text-gray-500">Nothing needed from you right now.</p>;
  return (
    <ul className="space-y-3">
      {needs.map((n: PortalNeed) => (
        <li key={`${n.subject_id}-${n.need_type}`}>
          <NeedItem need={n} onDone={() => void reload()} />
        </li>
      ))}
    </ul>
  );
}

function NeedItem({ need, onDone }: { need: PortalNeed; onDone: () => void }) {
  const getToken = useToken();
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const submit = async () => {
    setMsg(null);
    try {
      await answerPortalNeed(await getToken(), need.subject_id, need.need_type, body, file);
      setMsg("Sent for staff review.");
      onDone();
    } catch (e) {
      setMsg(String(e));
    }
  };
  return (
    <form
      className="space-y-2 rounded border border-gray-200 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <p className="text-sm font-medium">
        {need.subject_name}: {need.label}
      </p>
      <textarea
        className="block w-full border p-1"
        placeholder="Add a note (optional if you attach a document)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <input
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <button
        type="submit"
        disabled={!body && !file}
        className="rounded bg-blue-700 px-2 py-1 text-white disabled:opacity-50"
      >
        Submit answer
      </button>
      {msg && <p className="text-xs text-gray-600">{msg}</p>}
    </form>
  );
}

function ReportsTab() {
  const getToken = useToken();
  const { data: reports, error } = useAsync(listPortalReports);
  const download = async (r: PortalReport) => {
    const blob = await fetchPortalReportPdf(await getToken(), r.id);
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `report-${r.id}.pdf`;
    a.click();
    URL.revokeObjectURL(href);
  };
  if (error) return <p className="text-red-600">{error}</p>;
  if (!reports) return <p className="text-gray-500">Loading…</p>;
  if (reports.length === 0) return <p className="text-gray-500">No reports yet.</p>;
  return (
    <ul className="divide-y divide-gray-100">
      {reports.map((r: PortalReport) => (
        <li key={r.id} className="flex items-center justify-between py-2">
          <span className="text-sm">
            {r.period_start} → {r.period_end}
          </span>
          <button className="text-blue-700" onClick={() => void download(r)}>
            Download PDF
          </button>
        </li>
      ))}
    </ul>
  );
}
