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

// ── Slice 2: rights, consent, authorizations, claim support ──────────────────

export interface ClaimSupport {
  claim_type: string;
  supported: boolean;
  missing: string[];
}

export interface ClaimSupportResponse {
  matrix_status: string;
  claims: ClaimSupport[];
  enforcement: { enforceable: boolean; active_authorization_id: number | null };
  biometrics: {
    active_biometric_consent: boolean;
    biometrics_blocked: boolean;
    biometric_features_enabled: boolean;
  };
}

export interface RightsRecord {
  id: number;
  type: string;
  grants_enforcement_right: boolean;
  file_name: string;
  rights_date: string | null;
  expires_on: string | null;
  coverage: string | null;
  status: string;
}

export interface ConsentRecord {
  id: number;
  type: string;
  file_name: string;
  signer_name: string;
  signed_date: string;
  status: string;
}

export interface Authorization {
  id: number;
  subject_id: number | null;
  signer_name: string;
  authorized_date: string;
  status: string;
  notes: string | null;
  has_file: boolean;
}

const base = (wsId: number, sid: number) => `/workspaces/${wsId}/subjects/${sid}`;

export const getClaimSupport = (token: string, wsId: number, sid: number) =>
  request<ClaimSupportResponse>(token, `${base(wsId, sid)}/claim-support`);

export const listRights = (token: string, wsId: number, sid: number) =>
  request<RightsRecord[]>(token, `${base(wsId, sid)}/rights`);

export const createRights = (token: string, wsId: number, sid: number, form: FormData) =>
  request<RightsRecord>(token, `${base(wsId, sid)}/rights`, { method: "POST", body: form });

export const revokeRights = (
  token: string,
  wsId: number,
  sid: number,
  rid: number,
  reason: string,
) =>
  request<RightsRecord>(token, `${base(wsId, sid)}/rights/${rid}/revoke`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const rightsFileUrl = (token: string, wsId: number, sid: number, rid: number) =>
  request<{ url: string }>(token, `${base(wsId, sid)}/rights/${rid}/file`);

export const listConsent = (token: string, wsId: number, sid: number) =>
  request<ConsentRecord[]>(token, `${base(wsId, sid)}/consent`);

export const createConsent = (token: string, wsId: number, sid: number, form: FormData) =>
  request<ConsentRecord>(token, `${base(wsId, sid)}/consent`, { method: "POST", body: form });

export const revokeConsent = (
  token: string,
  wsId: number,
  sid: number,
  cid: number,
  reason: string,
) =>
  request<ConsentRecord>(token, `${base(wsId, sid)}/consent/${cid}/revoke`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const listSubjectAuthorizations = (token: string, wsId: number, sid: number) =>
  request<Authorization[]>(token, `${base(wsId, sid)}/authorizations`);

export const listWorkspaceAuthorizations = (token: string, wsId: number) =>
  request<Authorization[]>(token, `/workspaces/${wsId}/authorizations`);

export const createSubjectAuthorization = (
  token: string,
  wsId: number,
  sid: number,
  form: FormData,
) => request<Authorization>(token, `${base(wsId, sid)}/authorizations`, { method: "POST", body: form });

export const createWorkspaceAuthorization = (token: string, wsId: number, form: FormData) =>
  request<Authorization>(token, `/workspaces/${wsId}/authorizations`, { method: "POST", body: form });

export const revokeAuthorization = (token: string, wsId: number, aid: number, reason: string) =>
  request<Authorization>(token, `/workspaces/${wsId}/authorizations/${aid}/revoke`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
