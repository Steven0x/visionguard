import { useEffect, useState } from "react";
import { createWorkspace, listWorkspaces, type Workspace } from "../api";
import { useToken } from "../useToken";

export function WorkspaceList({
  isAdmin,
  onOpen,
}: {
  isAdmin: boolean;
  onOpen: (id: number) => void;
}) {
  const getToken = useToken();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      setWorkspaces(await listWorkspaces(await getToken()));
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Workspaces</h2>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <ul className="divide-y divide-gray-100">
        {workspaces.map((w) => (
          <li key={w.id} className="flex items-center justify-between py-2">
            <div>
              <button className="font-medium text-blue-700" onClick={() => onOpen(w.id)}>
                {w.name}
              </button>
              <span className="ml-2 text-sm text-gray-500">{w.plan}</span>
            </div>
          </li>
        ))}
        {workspaces.length === 0 && <li className="py-2 text-gray-500">No workspaces yet.</li>}
      </ul>

      {isAdmin && (
        <form
          className="flex flex-wrap items-end gap-2 rounded border border-gray-200 p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            try {
              await createWorkspace(await getToken(), {
                name: String(form.get("name") ?? ""),
                plan: String(form.get("plan") ?? "starter") || "starter",
                contact_email: String(form.get("contact_email") ?? "") || null,
              });
              e.currentTarget.reset();
              await reload();
            } catch (err) {
              setError(String(err));
            }
          }}
        >
          <input name="name" required placeholder="Agency name" className="border p-1" />
          <input name="plan" defaultValue="starter" placeholder="Plan" className="border p-1" />
          <input name="contact_email" placeholder="Contact email" className="border p-1" />
          <button className="rounded bg-blue-700 px-2 py-1 text-white">Create workspace</button>
        </form>
      )}
    </div>
  );
}
