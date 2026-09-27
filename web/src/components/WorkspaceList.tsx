import { useEffect, useState } from "react";
import { createWorkspace, listWorkspaces, type Workspace } from "../api";
import { useToken } from "../useToken";

// Kept in sync with WORKSPACE_PLANS in api/app/services/workspaces.py.
const PLANS = ["starter", "pro", "enterprise"] as const;

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
      setError(e instanceof Error ? e.message : String(e));
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

      {isAdmin && <CreateWorkspaceForm onCreated={reload} setError={setError} />}
    </div>
  );
}

function CreateWorkspaceForm({
  onCreated,
  setError,
}: {
  onCreated: () => Promise<void>;
  setError: (msg: string | null) => void;
}) {
  const getToken = useToken();
  const [name, setName] = useState("");
  const [plan, setPlan] = useState<(typeof PLANS)[number]>("starter");
  const [email, setEmail] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; email?: string }>({});
  const [submitting, setSubmitting] = useState(false);

  const validate = (): boolean => {
    const errs: { name?: string; email?: string } = {};
    if (!name.trim()) errs.name = "Name is required.";
    if (email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      errs.email = "Enter a valid email address.";
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  return (
    <form
      className="space-y-3 rounded border border-gray-200 p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        if (!validate() || submitting) return;
        setSubmitting(true);
        try {
          await createWorkspace(await getToken(), {
            name: name.trim(),
            plan,
            contact_email: email.trim() || null,
          });
          setName("");
          setPlan("starter");
          setEmail("");
          setFieldErrors({});
          await onCreated();
        } catch (err) {
          // Shows the real API error (CORS headers are now sent on errors too).
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <h3 className="font-medium">Create workspace</h3>
      <label className="block text-sm">
        <span className="text-gray-600">Name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-0.5 block w-64 border p-1"
          aria-invalid={!!fieldErrors.name}
        />
        {fieldErrors.name && <span className="text-xs text-red-600">{fieldErrors.name}</span>}
      </label>
      <label className="block text-sm">
        <span className="text-gray-600">Plan</span>
        <select
          value={plan}
          onChange={(e) => setPlan(e.target.value as (typeof PLANS)[number])}
          className="mt-0.5 block w-64 border p-1"
        >
          {PLANS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-sm">
        <span className="text-gray-600">Contact email</span>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="optional"
          className="mt-0.5 block w-64 border p-1"
          aria-invalid={!!fieldErrors.email}
        />
        {fieldErrors.email && <span className="text-xs text-red-600">{fieldErrors.email}</span>}
      </label>
      <button
        className="rounded bg-blue-700 px-2 py-1 text-white disabled:opacity-50"
        disabled={submitting}
      >
        {submitting ? "Creating…" : "Create workspace"}
      </button>
    </form>
  );
}
