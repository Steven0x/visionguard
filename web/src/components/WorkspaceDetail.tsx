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
import { useToken } from "../useToken";
import { SubjectImport } from "./SubjectImport";

const splitList = (v: string) =>
  v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

export function WorkspaceDetail({
  workspaceId,
  isAdmin,
  onBack,
}: {
  workspaceId: number;
  isAdmin: boolean;
  onBack: () => void;
}) {
  const getToken = useToken();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const token = await getToken();
      setDetail(await getWorkspace(token, workspaceId));
      setSubjects(
        await listSubjects(token, workspaceId, showArchived ? "all" : "active"),
      );
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, showArchived]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onAddSubject = async (form: FormData) => {
    setError(null);
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
      setError(String(e));
    }
  };

  if (!detail) return <p className="text-gray-500">Loading…{error}</p>;

  return (
    <div className="space-y-6">
      <button className="text-sm text-blue-700" onClick={onBack}>
        ← All workspaces
      </button>
      <h2 className="text-xl font-semibold">{detail.name}</h2>

      {isAdmin && <WorkspaceEditor detail={detail} onSaved={reload} />}
      {isAdmin && <AllowlistEditor detail={detail} onChanged={reload} />}

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Subjects ({subjects.length})</h3>
          <label className="text-sm">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />{" "}
            show archived
          </label>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="p-1">Legal name</th>
              <th className="p-1">Handles</th>
              <th className="p-1">Residence</th>
              <th className="p-1">Biometrics</th>
              <th className="p-1">Status</th>
              <th className="p-1"></th>
            </tr>
          </thead>
          <tbody>
            {subjects.map((s) => (
              <tr key={s.id} className="border-t border-gray-100">
                <td className="p-1">{s.legal_name}</td>
                <td className="p-1">{s.handles.join(", ")}</td>
                <td className="p-1">{s.residence_state ?? "—"}</td>
                <td className="p-1">
                  {s.biometrics_blocked ? (
                    <span className="text-amber-700">blocked</span>
                  ) : (
                    <span className="text-green-700">allowed</span>
                  )}
                </td>
                <td className="p-1">{s.status}</td>
                <td className="p-1">
                  {s.status === "active" && (
                    <button
                      className="text-red-700"
                      onClick={async () => {
                        await archiveSubject(await getToken(), workspaceId, s.id);
                        await reload();
                      }}
                    >
                      archive
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void onAddSubject(new FormData(e.currentTarget));
            e.currentTarget.reset();
          }}
        >
          <input name="legal_name" required placeholder="Legal name" className="border p-1" />
          <input name="stage_names" placeholder="Stage names (comma)" className="border p-1" />
          <input name="handles" placeholder="Handles (comma)" className="border p-1" />
          <input name="residence_state" placeholder="ST" maxLength={2} className="w-14 border p-1" />
          <input name="notes" placeholder="Notes" className="border p-1" />
          <button className="rounded bg-blue-700 px-2 py-1 text-white">Add subject</button>
        </form>
      </section>

      <SubjectImport workspaceId={workspaceId} onImported={reload} />
    </div>
  );
}

function WorkspaceEditor({ detail, onSaved }: { detail: Detail; onSaved: () => void }) {
  const getToken = useToken();
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded border border-gray-200 p-3"
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
      <input name="contact_name" defaultValue={detail.contact_name ?? ""} placeholder="Contact name" className="border p-1" />
      <input name="contact_email" defaultValue={detail.contact_email ?? ""} placeholder="Contact email" className="border p-1" />
      <input name="plan" defaultValue={detail.plan} placeholder="Plan" className="border p-1" />
      <button className="rounded bg-gray-800 px-2 py-1 text-white">Save workspace</button>
    </form>
  );
}

function AllowlistEditor({ detail, onChanged }: { detail: Detail; onChanged: () => void }) {
  const getToken = useToken();
  return (
    <section className="space-y-2 rounded border border-gray-200 p-3">
      <h3 className="font-medium">Allowlist</h3>
      <ul className="text-sm">
        {detail.allowlist.map((e) => (
          <li key={e.id} className="flex items-center gap-2">
            <span className="text-gray-500">{e.kind}</span>
            <span>{e.value}</span>
            <button
              className="text-red-700"
              onClick={async () => {
                await removeAllowlist(await getToken(), detail.id, e.id);
                onChanged();
              }}
            >
              remove
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex items-end gap-2"
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
        <select name="kind" className="border p-1">
          <option value="domain">domain</option>
          <option value="handle">handle</option>
          <option value="url">url</option>
          <option value="account">account</option>
        </select>
        <input name="value" required placeholder="value" className="border p-1" />
        <button className="rounded bg-blue-700 px-2 py-1 text-white">Add</button>
      </form>
    </section>
  );
}
