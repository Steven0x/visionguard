import { useState } from "react";
import { createWorkspace, type Workspace } from "../api";
import { errorText } from "../errors";
import { useToken } from "../useToken";
import { Button, Card, EmptyState, Input, Select } from "./ui";

// Kept in sync with WORKSPACE_PLANS in api/app/services/workspaces.py.
const PLANS = ["starter", "pro", "enterprise"] as const;

export function WorkspaceList({
  workspaces,
  isAdmin,
  onOpen,
  onReload,
}: {
  workspaces: Workspace[];
  isAdmin: boolean;
  onOpen: (id: number) => void;
  onReload: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Workspaces</h1>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {workspaces.length === 0 ? (
        <EmptyState
          title="No workspaces yet"
          description={
            isAdmin
              ? "Create the first workspace to start enforcing for an agency."
              : "Ask an admin to grant you access to a workspace."
          }
        />
      ) : (
        <Card bodyClassName="p-0">
          <ul className="divide-y divide-line">
            {workspaces.map((w) => (
              <li key={w.id} className="flex items-center justify-between px-4 py-3">
                <button
                  className="text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
                  onClick={() => onOpen(w.id)}
                >
                  {w.name}
                </button>
                <span className="text-xs text-fg-muted">{w.plan}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {isAdmin && <CreateWorkspaceForm onCreated={onReload} setError={setError} />}
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
    <Card title="Create workspace" className="max-w-md">
      <form
        className="space-y-3"
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
            setError(errorText(err));
          } finally {
            setSubmitting(false);
          }
        }}
      >
        <div>
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={!!fieldErrors.name}
          />
          {fieldErrors.name && (
            <span className="text-xs text-red-600 dark:text-red-400">{fieldErrors.name}</span>
          )}
        </div>
        <Select
          label="Plan"
          value={plan}
          onChange={(e) => setPlan(e.target.value as (typeof PLANS)[number])}
        >
          {PLANS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
        <div>
          <Input
            label="Contact email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="optional"
            aria-invalid={!!fieldErrors.email}
          />
          {fieldErrors.email && (
            <span className="text-xs text-red-600 dark:text-red-400">{fieldErrors.email}</span>
          )}
        </div>
        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create workspace"}
        </Button>
      </form>
    </Card>
  );
}
