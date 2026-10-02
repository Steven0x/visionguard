import { useCallback, useEffect, useState } from "react";
import {
  addAllowlist,
  archiveSubject,
  createSubject,
  getWorkspace,
  listSubjects,
  removeAllowlist,
  updateWorkspace,
  type Subject,
  type WorkspaceDetail as Detail,
} from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { BillingPanel } from "./BillingPanel";
import { CasesSection } from "./CasesSection";
import { DiscoverySettingsEditor } from "./DiscoverySettingsEditor";
import { FollowUpsSection } from "./FollowUpsSection";
import { ReportsSection } from "./ReportsSection";
import { ReviewInbox } from "./ReviewInbox";
import { SubjectDetail } from "./SubjectDetail";
import { SubjectImport } from "./SubjectImport";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  SkeletonRows,
  Table,
  TD,
  TH,
  THead,
  TR,
} from "./ui";

export type Section =
  | "inbox"
  | "cases"
  | "followups"
  | "reports"
  | "subjects"
  | "settings";

const SECTION_TITLE: Record<Section, string> = {
  inbox: "Review inbox",
  cases: "Cases",
  followups: "Follow-ups",
  reports: "Reports",
  subjects: "Subjects",
  settings: "Settings",
};

const splitList = (v: string) =>
  v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

export function WorkspaceDetail({
  workspaceId,
  section,
  isAdmin,
  keepBlurDefault,
}: {
  workspaceId: number;
  section: Section;
  isAdmin: boolean;
  keepBlurDefault: boolean;
}) {
  const getToken = useToken();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [openSubject, setOpenSubject] = useState<Subject | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addingSubject, setAddingSubject] = useState(false);

  const reload = useCallback(async () => {
    try {
      const token = await getToken();
      setDetail(await getWorkspace(token, workspaceId));
      setSubjects(await listSubjects(token, workspaceId, showArchived ? "all" : "active"));
    } catch (e) {
      setError(errorText(e));
    }
  }, [getToken, workspaceId, showArchived]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Changing workspace resets any open subject.
  useEffect(() => {
    setOpenSubject(null);
  }, [workspaceId, section]);

  const onAddSubject = async (form: FormData) => {
    setError(null);
    setAddingSubject(true);
    try {
      await createSubject(await getToken(), workspaceId, {
        legal_name: String(form.get("legal_name") ?? ""),
        stage_names: splitList(String(form.get("stage_names") ?? "")),
        handles: splitList(String(form.get("handles") ?? "")),
        residence_state: String(form.get("residence_state") ?? "") || null,
        notes: String(form.get("notes") ?? "") || null,
      });
      await reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setAddingSubject(false);
    }
  };

  if (!detail) return <SkeletonRows rows={5} />;

  if (section === "subjects" && openSubject) {
    return (
      <SubjectDetail
        workspaceId={workspaceId}
        subjectId={openSubject.id}
        subjectName={openSubject.legal_name}
        isAdmin={isAdmin}
        onBack={() => {
          setOpenSubject(null);
          void reload();
        }}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-fg-muted">{detail.name}</p>
        <h1 className="text-xl font-semibold">{SECTION_TITLE[section]}</h1>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {section === "inbox" && (
        <ReviewInbox workspaceId={workspaceId} isAdmin={isAdmin} keepBlurDefault={keepBlurDefault} />
      )}
      {section === "cases" && <CasesSection workspaceId={workspaceId} isAdmin={isAdmin} />}
      {section === "followups" && <FollowUpsSection workspaceId={workspaceId} />}
      {section === "reports" && <ReportsSection workspaceId={workspaceId} subjects={subjects} />}

      {section === "subjects" && (
        <div className="space-y-5">
          <Card
            title={`Subjects (${subjects.length})`}
            bodyClassName="p-0"
            actions={
              <label className="flex items-center gap-1.5 text-xs text-fg-muted">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                show archived
              </label>
            }
          >
            {subjects.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="No subjects yet"
                  description="Add a subject below, or import a roster as CSV."
                />
              </div>
            ) : (
              <Table>
                <THead>
                  <tr>
                    <TH>Legal name</TH>
                    <TH>Handles</TH>
                    <TH>Residence</TH>
                    <TH>Biometrics</TH>
                    <TH>Status</TH>
                    <TH />
                  </tr>
                </THead>
                <tbody>
                  {subjects.map((s) => (
                    <TR key={s.id}>
                      <TD>
                        <button
                          className="font-medium text-primary hover:underline"
                          onClick={() => setOpenSubject(s)}
                        >
                          {s.legal_name}
                        </button>
                      </TD>
                      <TD className="text-fg-muted">{s.handles.join(", ") || "—"}</TD>
                      <TD className="text-fg-muted">{s.residence_state ?? "—"}</TD>
                      <TD>
                        {s.biometrics_blocked ? (
                          <Badge tone="amber">blocked</Badge>
                        ) : (
                          <Badge tone="green">allowed</Badge>
                        )}
                      </TD>
                      <TD className="text-fg-muted">{s.status}</TD>
                      <TD>
                        {s.status === "active" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-600 dark:text-red-400"
                            onClick={async () => {
                              await archiveSubject(await getToken(), workspaceId, s.id);
                              await reload();
                            }}
                          >
                            archive
                          </Button>
                        )}
                      </TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <Card title="Add subject" className="max-w-3xl">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.currentTarget);
                e.currentTarget.reset();
                void onAddSubject(form);
              }}
            >
              <Input name="legal_name" required aria-label="Legal name" placeholder="Legal name" />
              <Input name="stage_names" aria-label="Stage names" placeholder="Stage names (comma)" />
              <Input name="handles" aria-label="Handles" placeholder="Handles (comma)" />
              <Input
                name="residence_state"
                aria-label="Residence state"
                placeholder="ST"
                maxLength={2}
                className="w-16"
              />
              <Input name="notes" aria-label="Notes" placeholder="Notes" />
              <Button type="submit" disabled={addingSubject}>
                {addingSubject ? "Adding…" : "Add subject"}
              </Button>
            </form>
          </Card>

          <SubjectImport workspaceId={workspaceId} onImported={reload} />
        </div>
      )}

      {section === "settings" && isAdmin && (
        <div className="space-y-5">
          <WorkspaceEditor detail={detail} onSaved={reload} />
          <AllowlistEditor detail={detail} onChanged={reload} />
          <DiscoverySettingsEditor workspaceId={workspaceId} />
          <BillingPanel workspaceId={workspaceId} />
        </div>
      )}
    </div>
  );
}

function WorkspaceEditor({ detail, onSaved }: { detail: Detail; onSaved: () => void }) {
  const getToken = useToken();
  return (
    <Card title="Workspace" className="max-w-3xl">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          await updateWorkspace(await getToken(), detail.id, {
            contact_name: String(form.get("contact_name") ?? "") || null,
            contact_email: String(form.get("contact_email") ?? "") || null,
            plan: String(form.get("plan") ?? "") || undefined,
          });
          onSaved();
        }}
      >
        <Input
          name="contact_name"
          aria-label="Contact name"
          defaultValue={detail.contact_name ?? ""}
          placeholder="Contact name"
        />
        <Input
          name="contact_email"
          aria-label="Contact email"
          defaultValue={detail.contact_email ?? ""}
          placeholder="Contact email"
        />
        <Input name="plan" aria-label="Plan" defaultValue={detail.plan} placeholder="Plan" />
        <Button type="submit" variant="secondary">
          Save workspace
        </Button>
      </form>
    </Card>
  );
}

function AllowlistEditor({ detail, onChanged }: { detail: Detail; onChanged: () => void }) {
  const getToken = useToken();
  return (
    <Card title="Allowlist" className="max-w-3xl">
      <ul className="mb-3 space-y-1 text-sm">
        {detail.allowlist.length === 0 && <li className="text-fg-muted">No entries.</li>}
        {detail.allowlist.map((e) => (
          <li key={e.id} className="flex items-center gap-2">
            <Badge tone="gray">{e.kind}</Badge>
            <span>{e.value}</span>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-600 dark:text-red-400"
              onClick={async () => {
                await removeAllowlist(await getToken(), detail.id, e.id);
                onChanged();
              }}
            >
              remove
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          await addAllowlist(await getToken(), detail.id, {
            kind: String(form.get("kind") ?? "domain"),
            value: String(form.get("value") ?? ""),
          });
          e.currentTarget.reset();
          onChanged();
        }}
      >
        <Select name="kind" aria-label="Allowlist kind" className="w-32">
          <option value="domain">domain</option>
          <option value="handle">handle</option>
          <option value="url">url</option>
          <option value="account">account</option>
        </Select>
        <Input name="value" required aria-label="Allowlist value" placeholder="value" />
        <Button type="submit">Add</Button>
      </form>
    </Card>
  );
}
