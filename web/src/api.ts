const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Me {
  id: number;
  email: string;
  role: "admin" | "reviewer";
  all_workspaces: boolean;
  review_keep_blur: boolean;
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

// ── Slice 3: assets & keywords ───────────────────────────────────────────────

export type AssetStatus = "pending" | "processing" | "ready" | "failed";

export interface Asset {
  id: number;
  subject_id: number;
  file_name: string;
  content_type: string;
  size_bytes: number;
  status: AssetStatus;
  sha256: string | null;
  phash: string | null;
  duplicate_of_asset_id: number | null;
  error: string | null;
  attempts: number;
}

export interface Keyword {
  id: number;
  keyword: string;
}

export const listAssets = (token: string, wsId: number, sid: number) =>
  request<Asset[]>(token, `${base(wsId, sid)}/assets`);

export const uploadAsset = (token: string, wsId: number, sid: number, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<Asset>(token, `${base(wsId, sid)}/assets`, { method: "POST", body: form });
};

export const deleteAsset = (token: string, wsId: number, sid: number, aid: number) =>
  request<void>(token, `${base(wsId, sid)}/assets/${aid}`, { method: "DELETE" });

export const retryAsset = (token: string, wsId: number, sid: number, aid: number) =>
  request<Asset>(token, `${base(wsId, sid)}/assets/${aid}/retry`, { method: "POST" });

export const assetThumbnailUrl = (token: string, wsId: number, sid: number, aid: number) =>
  request<{ url: string }>(token, `${base(wsId, sid)}/assets/${aid}/thumbnail`);

export const assetOriginalUrl = (token: string, wsId: number, sid: number, aid: number) =>
  request<{ url: string }>(token, `${base(wsId, sid)}/assets/${aid}/original`);

export const listKeywords = (token: string, wsId: number, sid: number) =>
  request<Keyword[]>(token, `${base(wsId, sid)}/keywords`);

export const addKeyword = (token: string, wsId: number, sid: number, keyword: string) =>
  request<Keyword>(token, `${base(wsId, sid)}/keywords`, {
    method: "POST",
    body: JSON.stringify({ keyword }),
  });

export const removeKeyword = (token: string, wsId: number, sid: number, kid: number) =>
  request<void>(token, `${base(wsId, sid)}/keywords/${kid}`, { method: "DELETE" });

// ── Slice 4: discovery ───────────────────────────────────────────────────────

export interface DiscoveryCandidate {
  id: number;
  run_id: number | null;
  provider: string;
  query: string | null;
  kind: "image" | "link";
  source_url: string;
  page_url: string | null;
  sha256: string | null;
  has_thumbnail: boolean;
  discovered_at: string;
}

export interface DiscoveryRun {
  id: number;
  kind: string;
  provider: string | null;
  status: "running" | "completed" | "partial" | "blocked" | "failed";
  calls_made: number;
  estimated_cost_cents: number;
  candidates_found: number;
  started_at: string;
  finished_at: string | null;
}

export interface DiscoverySettings {
  monthly_call_budget: number;
  scan_frequency: "off" | "daily" | "weekly";
  tineye_enabled: boolean;
  thumbnail_retention_days: number;
}

export const intakeUrls = (token: string, wsId: number, sid: number, urls: string[]) =>
  request<DiscoveryRun>(token, `${base(wsId, sid)}/discovery/intake`, {
    method: "POST",
    body: JSON.stringify({ urls }),
  });

export const scanNow = (token: string, wsId: number, sid: number) =>
  request<{ enqueued: number }>(token, `${base(wsId, sid)}/discovery/scan`, { method: "POST" });

export const listDiscoveryCandidates = (token: string, wsId: number, sid: number) =>
  request<DiscoveryCandidate[]>(token, `${base(wsId, sid)}/discovery/candidates`);

export const candidateThumbnailUrl = (token: string, wsId: number, sid: number, cid: number) =>
  request<{ url: string }>(token, `${base(wsId, sid)}/discovery/candidates/${cid}/thumbnail`);

export const listDiscoveryRuns = (token: string, wsId: number, sid: number) =>
  request<DiscoveryRun[]>(token, `${base(wsId, sid)}/discovery/runs`);

export const getDiscoverySettings = (token: string, wsId: number) =>
  request<DiscoverySettings>(token, `/workspaces/${wsId}/discovery/settings`);

export const updateDiscoverySettings = (
  token: string,
  wsId: number,
  body: Partial<DiscoverySettings>,
) =>
  request<DiscoverySettings>(token, `/workspaces/${wsId}/discovery/settings`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

// ── Slice 5: matching & the review inbox ─────────────────────────────────────

export type DismissReason =
  | "not_a_match"
  | "licensed"
  | "fair_use"
  | "own_account"
  | "other";

export const DISMISS_REASONS: DismissReason[] = [
  "not_a_match",
  "licensed",
  "fair_use",
  "own_account",
  "other",
];

export interface ScoreBreakdown {
  phash: { best_distance: number | null; asset_id: number | null; points: number };
  embedding: { best_similarity: number | null; asset_id: number | null; points: number };
  rules: { leak_domain: boolean; risky_keywords: string[]; points: number };
  visual_points: number;
  unverified: boolean;
}

export interface InboxItem {
  id: number;
  subject_id: number;
  subject_name: string;
  provider: string;
  kind: "image" | "link";
  source_url: string;
  page_url: string | null;
  score: number | null;
  score_breakdown: ScoreBreakdown | null;
  best_match_asset_id: number | null;
  has_found_thumbnail: boolean;
  has_asset_thumbnail: boolean;
  unverified: boolean;
  suggested_claim: string | null;
  supported_claims: string[];
  discovered_at: string;
}

export interface CaseStub {
  id: number;
  subject_id: number;
  candidate_id: number | null;
  matched_asset_id: number | null;
  claim_type: string;
  status: string;
  created_at: string;
}

export interface InboxFilters {
  subject_id?: number;
  min_score?: number;
  provider?: string;
  domain?: string;
  kind?: "image" | "link";
}

const wsBase = (wsId: number) => `/workspaces/${wsId}`;

export const listInbox = (token: string, wsId: number, filters: InboxFilters = {}) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== "" && v !== null) q.set(k, String(v));
  }
  const qs = q.toString();
  return request<InboxItem[]>(token, `${wsBase(wsId)}/review/inbox${qs ? `?${qs}` : ""}`);
};

export const confirmCandidate = (
  token: string,
  wsId: number,
  cid: number,
  claimType: string,
) =>
  request<CaseStub>(token, `${wsBase(wsId)}/review/candidates/${cid}/confirm`, {
    method: "POST",
    body: JSON.stringify({ claim_type: claimType }),
  });

export const dismissCandidate = (
  token: string,
  wsId: number,
  cid: number,
  reason: DismissReason,
) =>
  request<void>(token, `${wsBase(wsId)}/review/candidates/${cid}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const reopenCandidate = (token: string, wsId: number, cid: number, note: string) =>
  request<void>(token, `${wsBase(wsId)}/review/candidates/${cid}/reopen`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const bulkDismiss = (
  token: string,
  wsId: number,
  body: { domain?: string; account?: string; reason: DismissReason; dry_run: boolean },
) =>
  request<{ count: number; applied: boolean }>(token, `${wsBase(wsId)}/review/bulk-dismiss`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const foundThumbnailUrl = (token: string, wsId: number, cid: number) =>
  request<{ url: string }>(token, `${wsBase(wsId)}/review/candidates/${cid}/found-thumbnail`);

export const assetMatchThumbnailUrl = (token: string, wsId: number, cid: number) =>
  request<{ url: string }>(token, `${wsBase(wsId)}/review/candidates/${cid}/asset-thumbnail`);

export const listCases = (token: string, wsId: number) =>
  request<CaseStub[]>(token, `${wsBase(wsId)}/review/cases`);

export const updateReviewPrefs = (token: string, keepBlur: boolean) =>
  request<{ review_keep_blur: boolean }>(token, `/me/review-prefs`, {
    method: "PUT",
    body: JSON.stringify({ keep_blur: keepBlur }),
  });
