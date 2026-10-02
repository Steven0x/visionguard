const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Me {
  id: number;
  email: string;
  role: "admin" | "reviewer" | "agency";
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
    throw new Error(formatDetail(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Turn a FastAPI error `detail` (string, or a 422 array of {msg,loc}) into a readable line. */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d),
      )
      .join("; ");
  }
  return JSON.stringify(detail);
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
  /** A biometric-gated CLIP embedding exists. False on a ready asset → exact-match-only. */
  has_embedding: boolean;
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

// ── Slice 6: cases & lifecycle ───────────────────────────────────────────────

export type CaseStatus =
  | "discovered"
  | "confirmed"
  | "dismissed"
  | "filed"
  | "removed"
  | "countered"
  | "escalated"
  | "withdrawn"
  | "monitoring"
  | "recovered"
  | "closed";

export interface CaseRow {
  id: number;
  subject_id: number;
  candidate_id: number | null;
  matched_asset_id: number | null;
  claim_type: string;
  status: CaseStatus;
  sensitive: boolean;
  source_url: string | null;
  offender_key: string | null;
  assigned_staff_id: number | null;
  due_at: string | null;
  overdue: boolean;
  removal_proposed_at: string | null;
  reappearance_proposed_at: string | null;
  removal_unverified_at: string | null;
  created_at: string;
}

export interface CaseEvent {
  id: number;
  kind: "created" | "transition" | "claim_change" | "assignment" | "link";
  from_status: string | null;
  to_status: string | null;
  related_case_id: number | null;
  actor_staff_id: number | null;
  reason: string | null;
  note: string | null;
  created_at: string;
}

export interface CaseNote {
  id: number;
  author_staff_id: number | null;
  body: string;
  created_at: string;
}

export interface CaseDetail {
  case: CaseRow;
  allowed_transitions: CaseStatus[];
  timeline: CaseEvent[];
  notes: CaseNote[];
}

export interface OffenderGroup {
  offender_key: string;
  total: number;
  open: number;
}

export interface CaseFilters {
  subject_id?: number;
  status?: CaseStatus;
  claim_type?: string;
  offender_key?: string;
  assigned_staff_id?: number;
  overdue?: boolean;
  min_age_days?: number;
}

export const listCasesFiltered = (token: string, wsId: number, filters: CaseFilters = {}) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== "" && v !== null) q.set(k, String(v));
  }
  const qs = q.toString();
  return request<CaseRow[]>(token, `${wsBase(wsId)}/cases${qs ? `?${qs}` : ""}`);
};

export const listOffenders = (token: string, wsId: number) =>
  request<OffenderGroup[]>(token, `${wsBase(wsId)}/cases/offenders`);

export const getCaseDetail = (token: string, wsId: number, caseId: number) =>
  request<CaseDetail>(token, `${wsBase(wsId)}/cases/${caseId}`);

export const transitionCase = (
  token: string,
  wsId: number,
  caseId: number,
  toStatus: CaseStatus,
  opts: { reason?: string; note?: string } = {},
) =>
  request<CaseRow>(token, `${wsBase(wsId)}/cases/${caseId}/transition`, {
    method: "POST",
    body: JSON.stringify({ to_status: toStatus, ...opts }),
  });

export const changeCaseClaim = (
  token: string,
  wsId: number,
  caseId: number,
  claimType: string,
  note: string,
) =>
  request<CaseRow>(token, `${wsBase(wsId)}/cases/${caseId}/claim`, {
    method: "POST",
    body: JSON.stringify({ claim_type: claimType, note }),
  });

export const refileCase = (
  token: string,
  wsId: number,
  caseId: number,
  claimType: string,
  note: string,
) =>
  request<CaseRow>(token, `${wsBase(wsId)}/cases/${caseId}/refile`, {
    method: "POST",
    body: JSON.stringify({ claim_type: claimType, note }),
  });

export const addCaseNote = (token: string, wsId: number, caseId: number, body: string) =>
  request<CaseNote>(token, `${wsBase(wsId)}/cases/${caseId}/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });

export const assignCase = (
  token: string,
  wsId: number,
  caseId: number,
  staffId: number | null,
) =>
  request<CaseRow>(token, `${wsBase(wsId)}/cases/${caseId}/assign`, {
    method: "POST",
    body: JSON.stringify({ staff_id: staffId }),
  });

/** Explicit, audited action to mark a case not sensitive so report thumbnails may render for it.
 * Refused for ncii. */
export const clearCaseSensitive = (token: string, wsId: number, caseId: number) =>
  request<CaseRow>(token, `${wsBase(wsId)}/cases/${caseId}/clear-sensitive`, {
    method: "POST",
  });

// ── Slice 7: evidence ────────────────────────────────────────────────────────

export interface EvidenceCapture {
  id: number;
  kind: "auto" | "recapture" | "proof_of_removal" | "manual_upload" | "notice";
  status: "pending" | "sealed" | "failed" | "blocked";
  sensitive: boolean;
  requested_url: string | null;
  final_url: string | null;
  http_status: number | null;
  page_title: string | null;
  timestamp_status: "ok" | "untimestamped" | null;
  tsa_time: string | null;
  manifest_sha256: string | null;
  error: string | null;
  capture_finished_at: string | null;
  created_at: string;
}

export interface EvidenceArtifact {
  name: string;
  sha256: string;
  content_type: string;
  size_bytes: number;
}

export interface CustodyEvent {
  action: string;
  actor_staff_id: number | null;
  reason: string | null;
  detail: string | null;
  created_at: string;
}

export interface EvidenceDetail {
  capture: EvidenceCapture;
  artifacts: EvidenceArtifact[];
  custody: CustodyEvent[];
}

export interface VerifyResult {
  ok: boolean;
  files: Record<string, boolean>;
  manifest_ok: boolean;
  timestamp_ok: boolean | null;
}

const caseBase = (wsId: number, caseId: number) =>
  `/workspaces/${wsId}/cases/${caseId}/evidence`;

export const listEvidence = (token: string, wsId: number, caseId: number) =>
  request<EvidenceCapture[]>(token, caseBase(wsId, caseId));

export const getEvidence = (token: string, wsId: number, caseId: number, eid: number) =>
  request<EvidenceDetail>(token, `${caseBase(wsId, caseId)}/${eid}`);

export const recapture = (token: string, wsId: number, caseId: number) =>
  request<EvidenceCapture>(token, `${caseBase(wsId, caseId)}/recapture`, { method: "POST" });

export const uploadEvidence = (
  token: string,
  wsId: number,
  caseId: number,
  file: File,
  note: string,
) => {
  const form = new FormData();
  form.append("file", file);
  form.append("note", note);
  return request<EvidenceCapture>(token, `${caseBase(wsId, caseId)}/upload`, {
    method: "POST",
    body: form,
  });
};

export const verifyEvidence = (
  token: string,
  wsId: number,
  caseId: number,
  eid: number,
  reason: string,
) =>
  request<VerifyResult>(
    token,
    `${caseBase(wsId, caseId)}/${eid}/verify?reason=${encodeURIComponent(reason)}`,
  );

export const evidenceArtifactUrl = (
  token: string,
  wsId: number,
  caseId: number,
  eid: number,
  name: string,
  reason: string,
) =>
  request<{ url: string }>(
    token,
    `${caseBase(wsId, caseId)}/${eid}/artifacts/${name}?reason=${encodeURIComponent(reason)}`,
  );

export const evidencePackUrl = (wsId: number, caseId: number, reason: string, includeSensitive: boolean) =>
  `${API_BASE_URL}${caseBase(wsId, caseId)}/pack.pdf?reason=${encodeURIComponent(reason)}&include_sensitive=${includeSensitive}`;

// ── Notices (Slice 8) ─────────────────────────────────────────────────────────

export interface NoticeVersion {
  version: number;
  subject: string;
  body: string;
  edited_by_staff_id: number | null;
  created_at: string;
}

export interface Notice {
  id: number;
  case_id: number;
  platform: string;
  method: "email" | "web_form" | "portal";
  destination: string;
  claim_type: string;
  status: "draft" | "sent" | "delivery_failed" | "withdrawn";
  current_version: number;
  template_id: number;
  template_version: number;
  approved_by_staff_id: number | null;
  approved_at: string | null;
  sent_by_staff_id: number | null;
  sent_at: string | null;
  sealed_capture_id: number | null;
  created_at: string;
}

export interface NoticeDetail {
  notice: Notice | null;
  versions: NoticeVersion[];
  blockers: string[];
  can_send: boolean;
}

export interface NoticePacket {
  platform: string;
  method: string;
  destination: string;
  subject: string;
  body: string;
  checklist: string[];
  instructions: string;
}

export interface FilingLogRow {
  id: number;
  case_id: number;
  notice_id: number | null;
  platform: string;
  claim_type: string;
  method: string;
  outcome: string;
  ticket_number: string | null;
  response: string | null;
  filed_by_staff_id: number | null;
  created_at: string;
}

const noticeBase = (wsId: number, caseId: number) =>
  `/workspaces/${wsId}/cases/${caseId}/notice`;

export const getNotice = (token: string, wsId: number, caseId: number) =>
  request<NoticeDetail>(token, noticeBase(wsId, caseId));

export const createNoticeDraft = (token: string, wsId: number, caseId: number, platform: string) =>
  request<NoticeDetail>(token, noticeBase(wsId, caseId), {
    method: "POST",
    body: JSON.stringify({ platform }),
  });

export const editNoticeDraft = (
  token: string,
  wsId: number,
  caseId: number,
  subject: string,
  body: string,
) =>
  request<NoticeDetail>(token, noticeBase(wsId, caseId), {
    method: "PUT",
    body: JSON.stringify({ subject, body }),
  });

export const approveNotice = (
  token: string,
  wsId: number,
  caseId: number,
  fairUseConsidered: boolean,
) =>
  request<NoticeDetail>(token, `${noticeBase(wsId, caseId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ fair_use_considered: fairUseConsidered }),
  });

export const sendNotice = (token: string, wsId: number, caseId: number) =>
  request<Notice>(token, `${noticeBase(wsId, caseId)}/send`, { method: "POST" });

export const retrySendNotice = (token: string, wsId: number, caseId: number) =>
  request<Notice>(token, `${noticeBase(wsId, caseId)}/retry-send`, { method: "POST" });

export const getNoticePacket = (token: string, wsId: number, caseId: number) =>
  request<NoticePacket>(token, `${noticeBase(wsId, caseId)}/packet`);

export const recordHandSubmission = (
  token: string,
  wsId: number,
  caseId: number,
  ticketNumber: string,
  file: File,
) => {
  const form = new FormData();
  form.append("ticket_number", ticketNumber);
  form.append("file", file);
  return request<Notice>(token, `${noticeBase(wsId, caseId)}/hand-submission`, {
    method: "POST",
    body: form,
  });
};

export const withdrawNotice = (token: string, wsId: number, caseId: number, note: string) =>
  request<Notice>(token, `${noticeBase(wsId, caseId)}/withdraw`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const listFilingLog = (token: string, wsId: number, platform?: string) =>
  request<FilingLogRow[]>(
    token,
    `/workspaces/${wsId}/filing-log${platform ? `?platform=${encodeURIComponent(platform)}` : ""}`,
  );

// ── Slice 9: outcomes, re-upload watch, follow-ups, metrics ──────────────────

export type OutcomeKind = "removed" | "rejected" | "countered" | "no_response";

export interface NoticeOutcomeRow {
  id: number;
  case_id: number;
  notice_id: number;
  outcome: OutcomeKind;
  source: string;
  effective_at: string;
  note: string | null;
  supersedes_id: number | null;
  recorded_by_staff_id: number | null;
  created_at: string;
}

export interface OutcomesDetail {
  outcomes: NoticeOutcomeRow[];
  effective_outcome: OutcomeKind | null;
  removal_proposed_at: string | null;
  reappearance_proposed_at: string | null;
  removal_unverified_at: string | null;
}

export interface UrlRecheckRow {
  id: number;
  case_id: number;
  probed_url: string;
  http_status: number | null;
  result: "live" | "gone" | "error";
  detail: string | null;
  created_at: string;
}

export interface FollowUp {
  case_id: number;
  subject_id: number;
  claim_type: string;
  offender_key: string | null;
  due_at: string | null;
  source_url: string | null;
  reason: "overdue" | "removal_unverified";
}

export interface RemovalMetric {
  platform: string;
  claim_type: string;
  filed: number;
  withdrawn: number;
  removed: number;
  removed_verified: number;
  removed_staff_only: number;
  pending: number;
  removal_rate: number | null;
  median_days_to_removal: number | null;
}

const caseRoot = (wsId: number, caseId: number) =>
  `/workspaces/${wsId}/cases/${caseId}`;

export const getOutcomes = (token: string, wsId: number, caseId: number) =>
  request<OutcomesDetail>(token, `${caseRoot(wsId, caseId)}/outcomes`);

export const recordOutcome = (
  token: string,
  wsId: number,
  caseId: number,
  body: { outcome: OutcomeKind; effective_at?: string | null; note?: string | null },
) =>
  request<OutcomesDetail>(token, `${caseRoot(wsId, caseId)}/outcomes`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const dismissRemovalProposal = (
  token: string,
  wsId: number,
  caseId: number,
  note: string,
) =>
  request<OutcomesDetail>(
    token,
    `${caseRoot(wsId, caseId)}/outcomes/dismiss-removal-proposal`,
    { method: "POST", body: JSON.stringify({ note }) },
  );

export const reopenCase = (token: string, wsId: number, caseId: number) =>
  request<OutcomesDetail>(token, `${caseRoot(wsId, caseId)}/reopen`, { method: "POST" });

export const listRechecks = (token: string, wsId: number, caseId: number) =>
  request<UrlRecheckRow[]>(token, `${caseRoot(wsId, caseId)}/rechecks`);

export const listFollowUps = (token: string, wsId: number) =>
  request<FollowUp[]>(token, `/workspaces/${wsId}/follow-ups`);

export const getRemovalMetrics = (token: string, wsId: number) =>
  request<RemovalMetric[]>(token, `/workspaces/${wsId}/metrics/removals`);

// ── Slice 10: reports + internal metrics summary ─────────────────────────────

export interface ReportRow {
  id: number;
  subject_id: number | null;
  period_start: string;
  period_end: string;
  as_of: string;
  include_thumbnails: boolean;
  pdf_sha256: string;
  json_sha256: string;
  generated_by_staff_id: number | null;
  created_at: string;
}

export interface ProviderCost {
  provider: string;
  cost_cents: number;
}

export interface MetricsSummary {
  removals: RemovalMetric[];
  review_precision: number | null;
  wrong_filing_rate: number | null;
  re_upload_rate: number | null;
  review_minutes_per_case: number | null;
  provider_cost: ProviderCost[];
  provider_cost_total_cents: number;
}

export const generateReport = (
  token: string,
  wsId: number,
  body: {
    subject_id?: number | null;
    start: string;
    end: string;
    include_thumbnails?: boolean;
  },
) =>
  request<ReportRow>(token, `/workspaces/${wsId}/reports`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listReports = (token: string, wsId: number, subjectId?: number) =>
  request<ReportRow[]>(
    token,
    `/workspaces/${wsId}/reports${subjectId != null ? `?subject_id=${subjectId}` : ""}`,
  );

export const getMetricsSummary = (token: string, wsId: number) =>
  request<MetricsSummary>(token, `/workspaces/${wsId}/metrics/summary`);

/** Fetch a sealed report artifact WITH the bearer token (so it can't be a plain link), returning
 * a Blob the caller turns into a download. */
export async function fetchReportBlob(
  token: string,
  wsId: number,
  reportId: number,
  which: "pdf" | "json",
): Promise<Blob> {
  const path =
    which === "pdf"
      ? `/workspaces/${wsId}/reports/${reportId}.pdf`
      : `/workspaces/${wsId}/reports/${reportId}/inputs.json`;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`download failed (${res.status})`);
  return res.blob();
}

// ── Agency portal (Slice 12) ──────────────────────────────────────────────────
// All portal responses are minimized server-side; the workspace is resolved from the agency
// user's membership, so none of these take a workspace id.
export interface PortalContext {
  email: string;
  role: string;
  workspace_id: number;
  workspace_name: string;
}

export interface PortalSubject {
  id: number;
  legal_name: string;
  stage_names: string[];
  handles: string[];
  status: string;
}

export interface PortalCase {
  id: number;
  subject_id: number;
  claim_type: string;
  status: string;
  display_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface PortalTimelineEvent {
  from_status: string | null;
  to_status: string | null;
  created_at: string;
}

export interface PortalCaseDetail {
  case: PortalCase;
  timeline: PortalTimelineEvent[];
}

export interface PortalReport {
  id: number;
  subject_id: number | null;
  period_start: string;
  period_end: string;
  created_at: string;
}

export interface PortalNeed {
  subject_id: number;
  subject_name: string;
  need_type: string;
  label: string;
}

export const getPortalContext = (token: string) =>
  request<PortalContext>(token, "/portal/context");

export const listPortalSubjects = (token: string) =>
  request<PortalSubject[]>(token, "/portal/subjects");

export const listPortalCases = (token: string) =>
  request<PortalCase[]>(token, "/portal/cases");

export const getPortalCase = (token: string, caseId: number) =>
  request<PortalCaseDetail>(token, `/portal/cases/${caseId}`);

export const listPortalReports = (token: string) =>
  request<PortalReport[]>(token, "/portal/reports");

export const listPortalNeeds = (token: string) =>
  request<PortalNeed[]>(token, "/portal/needs");

export interface TipResult {
  submission_id: number;
  candidate_created: boolean;
  detail: string;
}

export const submitPortalTip = (token: string, subjectId: number, url: string) =>
  request<TipResult>(token, "/portal/tips", {
    method: "POST",
    body: JSON.stringify({ subject_id: subjectId, url }),
  });

/** Answer a "Needs from you" item with text and/or a PDF (multipart). */
export async function answerPortalNeed(
  token: string,
  subjectId: number,
  needType: string,
  body: string,
  file: File | null,
): Promise<{ submission_id: number; detail: string }> {
  const form = new FormData();
  form.append("subject_id", String(subjectId));
  form.append("need_type", needType);
  if (body) form.append("body", body);
  if (file) form.append("file", file);
  return request(token, "/portal/needs/answer", { method: "POST", body: form });
}

/** Download a sealed report PDF with the bearer token (never a plain link). */
export async function fetchPortalReportPdf(token: string, reportId: number): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/portal/reports/${reportId}.pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`download failed (${res.status})`);
  return res.blob();
}

// ── Billing (Slice 13) ─────────────────────────────────────────────────────────
// Pricing lives entirely in Stripe; the client only picks a plan + cadence and opens hosted
// Checkout / Customer Portal. Quantity is derived server-side (never sent).
export type BillingMode = "stripe" | "manual";
export type BillingPlanTier = "none" | "core" | "priority";
export type BillingCadence = "none" | "monthly" | "annual";
export type BillingStatusValue =
  | "none"
  | "trialing"
  | "active"
  | "past_due"
  | "canceled";

export interface BillingStatus {
  billing_mode: BillingMode;
  status: BillingStatusValue;
  plan_tier: BillingPlanTier;
  cadence: BillingCadence;
  quantity: number;
  current_period_end: string | null;
  grace_until: string | null;
  in_grace: boolean;
  suspended: boolean;
  priority: boolean;
  has_subscription: boolean;
  billing_contact_staff_id?: number | null;
  has_customer?: boolean;
}

export interface PortalBillingStatus extends BillingStatus {
  is_billing_contact: boolean;
  billing_contact_email: string | null;
}

// Staff admin
export const getBilling = (token: string, wsId: number) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing`);

export const setBillingMode = (token: string, wsId: number, mode: BillingMode) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing/mode`, {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });

export const createBillingCheckout = (
  token: string,
  wsId: number,
  planTier: BillingPlanTier,
  cadence: BillingCadence,
) =>
  request<{ url: string }>(token, `/workspaces/${wsId}/billing/checkout`, {
    method: "POST",
    body: JSON.stringify({ plan_tier: planTier, cadence }),
  });

export const openBillingPortal = (token: string, wsId: number) =>
  request<{ url: string }>(token, `/workspaces/${wsId}/billing/portal`, { method: "POST" });

export const applyOnboardingCredit = (token: string, wsId: number) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing/onboarding-credit`, {
    method: "POST",
  });

export const applyDesignPartnerCoupon = (token: string, wsId: number) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing/coupon`, { method: "POST" });

export const setBillingOverride = (
  token: string,
  wsId: number,
  body: { priority_override: boolean | null; discovery_frequency_override: string | null },
) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing/override`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const setBillingContact = (token: string, wsId: number, staffId: number) =>
  request<BillingStatus>(token, `/workspaces/${wsId}/billing/billing-contact`, {
    method: "PUT",
    body: JSON.stringify({ staff_id: staffId }),
  });

// Agency portal billing contact
export const getPortalBilling = (token: string) =>
  request<PortalBillingStatus>(token, "/portal/billing");

export const portalCreateCheckout = (
  token: string,
  planTier: BillingPlanTier,
  cadence: BillingCadence,
) =>
  request<{ url: string }>(token, "/portal/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ plan_tier: planTier, cadence }),
  });

export const portalOpenCustomerPortal = (token: string) =>
  request<{ url: string }>(token, "/portal/billing/portal", { method: "POST" });
