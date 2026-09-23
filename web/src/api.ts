const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Me {
  id: number;
  email: string;
  role: "admin" | "reviewer";
  all_workspaces: boolean;
}

export interface Workspace {
  id: number;
  name: string;
  slug: string;
  plan: string;
  contact_name: string | null;
  contact_email: string | null;
}

export interface AllowlistEntry {
  id: number;
  kind: "domain" | "handle" | "url" | "account";
  value: string;
  note: string | null;
}

export interface WorkspaceDetail extends Workspace {
  allowlist: AllowlistEntry[];
}

export interface Subject {
  id: number;
  legal_name: string;
  stage_names: string[];
  handles: string[];
  residence_state: string | null;
  biometrics_blocked: boolean;
  status: "active" | "archived";
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubjectInput {
  legal_name: string;
  stage_names: string[];
  handles: string[];
  residence_state: string | null;
  notes: string | null;
}

export interface PreviewRow {
  row_no: number;
  values: Record<string, unknown>;
  errors: string[];
}

export interface PreviewResponse {
  rows: PreviewRow[];
  has_errors: boolean;
}

async function request<T>(
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const fetchMe = (token: string) => request<Me>(token, "/me");

export const listWorkspaces = (token: string) =>
  request<Workspace[]>(token, "/workspaces");

export const createWorkspace = (token: string, body: Partial<Workspace>) =>
  request<Workspace>(token, "/workspaces", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getWorkspace = (token: string, id: number) =>
  request<WorkspaceDetail>(token, `/workspaces/${id}`);

export const updateWorkspace = (
  token: string,
  id: number,
  body: Partial<Workspace>,
) =>
  request<Workspace>(token, `/workspaces/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const addAllowlist = (
  token: string,
  id: number,
  body: { kind: string; value: string; note?: string | null },
) =>
  request<AllowlistEntry>(token, `/workspaces/${id}/allowlist`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const removeAllowlist = (token: string, id: number, entryId: number) =>
  request<void>(token, `/workspaces/${id}/allowlist/${entryId}`, {
    method: "DELETE",
  });

export const listSubjects = (
  token: string,
  id: number,
  status: "active" | "archived" | "all" = "active",
) => request<Subject[]>(token, `/workspaces/${id}/subjects?status=${status}`);

export const createSubject = (token: string, id: number, body: SubjectInput) =>
  request<Subject>(token, `/workspaces/${id}/subjects`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateSubject = (
  token: string,
  id: number,
  sid: number,
  body: SubjectInput,
) =>
  request<Subject>(token, `/workspaces/${id}/subjects/${sid}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const archiveSubject = (token: string, id: number, sid: number) =>
  request<Subject>(token, `/workspaces/${id}/subjects/${sid}/archive`, {
    method: "POST",
  });

function fileForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export const previewImport = (token: string, id: number, file: File) =>
  request<PreviewResponse>(token, `/workspaces/${id}/subjects/import/preview`, {
    method: "POST",
    body: fileForm(file),
  });

export const commitImport = (token: string, id: number, file: File) =>
  request<{ imported: number }>(
    token,
    `/workspaces/${id}/subjects/import/commit`,
    { method: "POST", body: fileForm(file) },
  );
