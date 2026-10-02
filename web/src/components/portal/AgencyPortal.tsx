import { UserButton } from "@clerk/clerk-react";
import { useCallback, useEffect, useState } from "react";
import {
  answerPortalNeed,
  fetchPortalReportPdf,
  getPortalBilling,
  getPortalCase,
  getPortalContext,
  listPortalCases,
  listPortalNeeds,
  listPortalReports,
  listPortalSubjects,
  portalCreateCheckout,
  portalOpenCustomerPortal,
  submitPortalTip,
  type BillingCadence,
  type BillingPlanTier,
  type CaseStatus,
  type PortalBillingStatus,
  type PortalCase,
  type PortalCaseDetail,
  type PortalContext,
  type PortalNeed,
  type PortalReport,
  type PortalSubject,
} from "../../api";
import { errorText } from "../../errors";
import { ThemeToggle } from "../ThemeToggle";
import {
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  SkeletonRows,
  StatusBadge,
  Tabs,
  Textarea,
  useToast,
} from "../ui";
import { useToken } from "../../useToken";
import { PortalShell } from "./PortalShell";

const DEV_AUTH = import.meta.env.VITE_DEV_AUTH === "1";

type Tab = "cases" | "subjects" | "needs" | "reports" | "billing";

const TABS: { key: Tab; label: string }[] = [
  { key: "cases", label: "Cases" },
  { key: "subjects", label: "Subjects" },
  { key: "needs", label: "Needs from you" },
  { key: "reports", label: "Reports" },
  { key: "billing", label: "Billing" },
];

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
        if (active) setError(errorText(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <EmptyState title="Couldn’t load your portal" description={error} />
      </div>
    );
  }
  if (!ctx) {
    return (
      <div className="mx-auto max-w-md p-8">
        <SkeletonRows rows={4} />
      </div>
    );
  }

  return (
    <PortalShell
      agencyName={ctx.workspace_name}
      email={ctx.email}
      topRight={
        <>
          <ThemeToggle />
          {!DEV_AUTH && <UserButton />}
        </>
      }
    >
      <div className="space-y-4">
        <BillingBanner />
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
        {tab === "cases" && <CasesTab />}
        {tab === "subjects" && <SubjectsTab />}
        {tab === "needs" && <NeedsTab />}
        {tab === "reports" && <ReportsTab />}
        {tab === "billing" && <BillingTab />}
      </div>
    </PortalShell>
  );
}

/** A red/amber banner shown on every tab when billing needs attention (grace or suspended). */
function BillingBanner() {
  const { data } = useAsync(getPortalBilling);
  if (!data) return null;
  if (data.suspended)
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-200">
        Billing is suspended. New monitoring and new subjects are paused — work on existing cases
        continues. {data.billing_contact_email ?? "Your billing contact"} can bring billing current
        under the Billing tab.
      </div>
    );
  if (data.in_grace)
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
        A payment is overdue. Please update billing before the grace period ends
        {data.grace_until ? ` (${data.grace_until.slice(0, 10)})` : ""}.
      </div>
    );
  return null;
}

function BillingTab() {
  const getToken = useToken();
  const { data, error } = useAsync<PortalBillingStatus>(getPortalBilling);
  const [plan, setPlan] = useState<BillingPlanTier>("core");
  const [cadence, setCadence] = useState<BillingCadence>("monthly");
  const [msg, setMsg] = useState<string | null>(null);

  const go = async (url: string) => {
    window.location.href = url;
  };
  const subscribe = async () => {
    setMsg(null);
    try {
      const { url } = await portalCreateCheckout(await getToken(), plan, cadence);
      await go(url);
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const manage = async () => {
    setMsg(null);
    try {
      const { url } = await portalOpenCustomerPortal(await getToken());
      await go(url);
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  if (error) return <ErrorNote message={error} />;
  if (!data) return <SkeletonRows rows={3} />;

  return (
    <Card title="Billing">
      <dl className="mb-4 grid grid-cols-2 gap-3 text-sm sm:max-w-md">
        <div>
          <dt className="text-xs text-fg-muted">Plan</dt>
          <dd className="font-medium">
            {data.plan_tier} ({data.cadence}) — {data.status}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-fg-muted">Talents billed</dt>
          <dd className="font-medium">{data.quantity}</dd>
        </div>
      </dl>

      {!data.is_billing_contact ? (
        <p className="text-sm text-fg-muted">
          {data.billing_contact_email
            ? `${data.billing_contact_email} manages billing for this workspace.`
            : "A billing contact has not been designated yet. Ask VisionGuard to set one."}
        </p>
      ) : (
        <div className="space-y-3">
          {!data.has_subscription && (
            <div className="flex flex-wrap items-end gap-2">
              <Select
                label="Plan"
                value={plan}
                onChange={(e) => setPlan(e.target.value as BillingPlanTier)}
              >
                <option value="core">Core</option>
                <option value="priority">Priority</option>
              </Select>
              <Select
                label="Cadence"
                value={cadence}
                onChange={(e) => setCadence(e.target.value as BillingCadence)}
              >
                <option value="monthly">Monthly</option>
                <option value="annual">Annual (2 months free)</option>
              </Select>
              <Button onClick={() => void subscribe()}>Subscribe</Button>
            </div>
          )}
          <Button variant="secondary" onClick={() => void manage()}>
            Manage billing (card, ACH, invoices)
          </Button>
        </div>
      )}
      {msg && <ErrorNote message={msg} className="mt-2" />}
    </Card>
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
      setError(errorText(e));
    }
  }, [getToken]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, reload };
}

function ErrorNote({ message, className }: { message: string; className?: string }) {
  return (
    <p className={`text-sm text-red-600 dark:text-red-400 ${className ?? ""}`}>{message}</p>
  );
}

function CasesTab() {
  const { data: cases, error } = useAsync(listPortalCases);
  const [open, setOpen] = useState<number | null>(null);
  if (error) return <ErrorNote message={error} />;
  if (!cases) return <SkeletonRows rows={4} />;
  if (open !== null) return <CaseDetail caseId={open} onBack={() => setOpen(null)} />;
  if (cases.length === 0)
    return <EmptyState title="No cases yet" description="Enforcement activity will appear here." />;
  return (
    <Card bodyClassName="p-0">
      <ul className="divide-y divide-line">
        {cases.map((c: PortalCase) => (
          <li key={c.id} className="flex items-center gap-3 px-4 py-3">
            <button
              className="text-sm font-semibold text-primary hover:underline"
              onClick={() => setOpen(c.id)}
            >
              Case #{c.id}
            </button>
            <span className="text-xs text-fg-muted">{c.claim_type}</span>
            {c.display_url && <span className="truncate text-xs text-fg-muted">{c.display_url}</span>}
            <span className="ml-auto">
              <StatusBadge status={c.status as CaseStatus} />
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function CaseDetail({ caseId, onBack }: { caseId: number; onBack: () => void }) {
  const { data, error } = useAsync<PortalCaseDetail>((t) => getPortalCase(t, caseId));
  if (error) return <ErrorNote message={error} />;
  if (!data) return <SkeletonRows rows={4} />;
  return (
    <div className="space-y-3">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back
      </Button>
      <Card
        title={
          <span className="flex items-center gap-2">
            Case #{data.case.id}
            <StatusBadge status={data.case.status as CaseStatus} />
          </span>
        }
      >
        <ol className="space-y-1 text-sm">
          {data.timeline.map((e, i) => (
            <li key={i} className="flex items-center gap-2 text-fg-muted">
              <span>
                {e.from_status ?? "—"} → {e.to_status ?? "—"}
              </span>
              <span className="text-xs">{e.created_at.slice(0, 10)}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function SubjectsTab() {
  const { data: subjects, error } = useAsync(listPortalSubjects);
  if (error) return <ErrorNote message={error} />;
  if (!subjects) return <SkeletonRows rows={4} />;
  return (
    <div className="space-y-4">
      {subjects.length === 0 ? (
        <EmptyState title="No subjects yet" description="VisionGuard adds the talents it protects." />
      ) : (
        <Card bodyClassName="p-0">
          <ul className="divide-y divide-line">
            {subjects.map((s: PortalSubject) => (
              <li key={s.id} className="flex items-center gap-2 px-4 py-3">
                <span className="text-sm font-medium">{s.legal_name}</span>
                <span className="text-xs text-fg-muted">{s.status}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <TipForm subjects={subjects} />
    </div>
  );
}

function TipForm({ subjects }: { subjects: PortalSubject[] }) {
  const getToken = useToken();
  const { toast } = useToast();
  const [subjectId, setSubjectId] = useState<number | "">("");
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const submit = async () => {
    setMsg(null);
    try {
      const r = await submitPortalTip(await getToken(), Number(subjectId), url);
      toast(r.detail, "success");
      setUrl("");
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <Card title="Submit a URL tip">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Select
          label="Subject"
          className="sm:max-w-xs"
          value={subjectId}
          onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">Choose a subject…</option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>
              {s.legal_name}
            </option>
          ))}
        </Select>
        <Input
          label="URL"
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button type="submit" disabled={!subjectId || !url}>
          Send tip
        </Button>
        {msg && <ErrorNote message={msg} />}
      </form>
    </Card>
  );
}

function NeedsTab() {
  const { data: needs, error, reload } = useAsync(listPortalNeeds);
  if (error) return <ErrorNote message={error} />;
  if (!needs) return <SkeletonRows rows={3} />;
  if (needs.length === 0)
    return <EmptyState title="You’re all caught up" description="Nothing is needed from you right now." />;
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
  const { toast } = useToast();
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const submit = async () => {
    setMsg(null);
    try {
      await answerPortalNeed(await getToken(), need.subject_id, need.need_type, body, file);
      toast("Sent for staff review.", "success");
      onDone();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <Card title={`${need.subject_name}: ${need.label}`}>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Textarea
          aria-label="Note"
          placeholder="Add a note (optional if you attach a document)"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <input
          type="file"
          accept="application/pdf"
          aria-label="Attach a PDF"
          className="block text-sm text-fg-muted file:mr-3 file:rounded-md file:border-0 file:bg-surface-muted file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-fg"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button type="submit" disabled={!body && !file}>
          Submit answer
        </Button>
        {msg && <ErrorNote message={msg} />}
      </form>
    </Card>
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
  if (error) return <ErrorNote message={error} />;
  if (!reports) return <SkeletonRows rows={3} />;
  if (reports.length === 0)
    return <EmptyState title="No reports yet" description="Monthly enforcement reports will appear here." />;
  return (
    <Card bodyClassName="p-0">
      <ul className="divide-y divide-line">
        {reports.map((r: PortalReport) => (
          <li key={r.id} className="flex items-center justify-between px-4 py-3">
            <span className="text-sm">
              {r.period_start} → {r.period_end}
            </span>
            <Button variant="secondary" size="sm" onClick={() => void download(r)}>
              Download PDF
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
