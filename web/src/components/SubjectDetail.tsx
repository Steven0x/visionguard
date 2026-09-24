import { useCallback, useEffect, useState } from "react";
import {
  type Authorization,
  type ClaimSupportResponse,
  type ConsentRecord,
  type RightsRecord,
  createConsent,
  createRights,
  createSubjectAuthorization,
  createWorkspaceAuthorization,
  getClaimSupport,
  listConsent,
  listRights,
  listSubjectAuthorizations,
  listWorkspaceAuthorizations,
  revokeAuthorization,
  revokeConsent,
  revokeRights,
  rightsFileUrl,
} from "../api";
import { useToken } from "../useToken";
import { ClaimSupportPanel } from "./ClaimSupportPanel";

const RIGHTS_TYPES = [
  "management_agreement",
  "photographer_license",
  "copyright_registration",
  "self_owned_declaration",
  "other",
];

/** Build multipart FormData from a form, pruning empty text fields and empty file inputs. */
function formData(formEl: HTMLFormElement): FormData {
  const fd = new FormData(formEl);
  for (const [key, value] of Array.from(fd.entries())) {
    if (typeof value === "string" && value.trim() === "") fd.delete(key);
    else if (value instanceof File && value.size === 0 && value.name === "") fd.delete(key);
  }
  return fd;
}

export function SubjectDetail({
  workspaceId,
  subjectId,
  subjectName,
  isAdmin,
  onBack,
}: {
  workspaceId: number;
  subjectId: number;
  subjectName: string;
  isAdmin: boolean;
  onBack: () => void;
}) {
  const getToken = useToken();
  const [claims, setClaims] = useState<ClaimSupportResponse | null>(null);
  const [rights, setRights] = useState<RightsRecord[]>([]);
  const [consent, setConsent] = useState<ConsentRecord[]>([]);
  const [subjectAuths, setSubjectAuths] = useState<Authorization[]>([]);
  const [workspaceAuths, setWorkspaceAuths] = useState<Authorization[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const t = await getToken();
      setClaims(await getClaimSupport(t, workspaceId, subjectId));
      setRights(await listRights(t, workspaceId, subjectId));
      setConsent(await listConsent(t, workspaceId, subjectId));
      setSubjectAuths(await listSubjectAuthorizations(t, workspaceId, subjectId));
      setWorkspaceAuths(await listWorkspaceAuthorizations(t, workspaceId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, subjectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const openDownload = async (rid: number) => {
    const { url } = await rightsFileUrl(await getToken(), workspaceId, subjectId, rid);
    window.open(url, "_blank");
  };

  return (
    <div className="space-y-6">
      <button className="text-sm text-blue-700" onClick={onBack}>
        ← Subjects
      </button>
      <h2 className="text-xl font-semibold">{subjectName}</h2>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {claims && <ClaimSupportPanel data={claims} />}

      {/* Rights */}
      <section className="space-y-2">
        <h3 className="font-medium">Rights records</h3>
        <ul className="text-sm">
          {rights.map((r) => (
            <li key={r.id} className="flex items-center gap-2 border-t border-gray-100 py-1">
              <span className="font-mono">{r.type}</span>
              {r.grants_enforcement_right && <span className="text-green-700">✓enf</span>}
              <span className="text-gray-500">{r.status}</span>
              {r.expires_on && <span className="text-gray-400">exp {r.expires_on}</span>}
              <button className="text-blue-700" onClick={() => void openDownload(r.id)}>
                file
              </button>
              {isAdmin && r.status === "active" && (
                <button
                  className="text-red-700"
                  onClick={() => void run(async () =>
                    revokeRights(await getToken(), workspaceId, subjectId, r.id, "revoked")
                  )}
                >
                  revoke
                </button>
              )}
            </li>
          ))}
        </ul>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = formData(e.currentTarget);
            e.currentTarget.reset();
            void run(async () => createRights(await getToken(), workspaceId, subjectId, fd));
          }}
        >
          <select name="type" className="border p-1">
            {RIGHTS_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <label className="text-sm">
            <input type="checkbox" name="grants_enforcement_right" value="true" /> grants enf.
          </label>
          <input name="expires_on" type="date" className="border p-1" />
          <input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" required />
          <button className="rounded bg-blue-700 px-2 py-1 text-white">Add rights</button>
        </form>
      </section>

      {/* Consent */}
      <section className="space-y-2">
        <h3 className="font-medium">Consent records</h3>
        <ul className="text-sm">
          {consent.map((c) => (
            <li key={c.id} className="flex items-center gap-2 border-t border-gray-100 py-1">
              <span className="font-mono">{c.type}</span>
              <span>{c.signer_name}</span>
              <span className="text-gray-400">{c.signed_date}</span>
              <span className="text-gray-500">{c.status}</span>
              {isAdmin && c.status === "active" && (
                <button
                  className="text-red-700"
                  onClick={() => void run(async () =>
                    revokeConsent(await getToken(), workspaceId, subjectId, c.id, "revoked")
                  )}
                >
                  revoke
                </button>
              )}
            </li>
          ))}
        </ul>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = formData(e.currentTarget);
            e.currentTarget.reset();
            void run(async () => createConsent(await getToken(), workspaceId, subjectId, fd));
          }}
        >
          <select name="type" className="border p-1">
            <option value="enforcement">enforcement</option>
            <option value="biometric">biometric</option>
          </select>
          <input name="signer_name" placeholder="Signer" required className="border p-1" />
          <input name="signed_date" type="date" required className="border p-1" />
          <input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" required />
          <button className="rounded bg-blue-700 px-2 py-1 text-white">Add consent</button>
        </form>
      </section>

      {/* Authorizations */}
      {isAdmin && (
        <section className="space-y-2">
          <h3 className="font-medium">Agent authorizations</h3>
          <ul className="text-sm">
            {[...subjectAuths, ...workspaceAuths].map((a) => (
              <li key={a.id} className="flex items-center gap-2 border-t border-gray-100 py-1">
                <span>{a.subject_id === null ? "workspace" : "subject"}</span>
                <span>{a.signer_name}</span>
                <span className="text-gray-400">{a.authorized_date}</span>
                <span className="text-gray-500">{a.status}</span>
                {a.status === "active" && (
                  <button
                    className="text-red-700"
                    onClick={() => void run(async () =>
                      revokeAuthorization(await getToken(), workspaceId, a.id, "revoked")
                    )}
                  >
                    revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-4">
            <AuthForm
              label="Add subject authorization"
              onSubmit={(fd) =>
                run(async () =>
                  createSubjectAuthorization(await getToken(), workspaceId, subjectId, fd),
                )
              }
            />
            <AuthForm
              label="Add workspace authorization"
              onSubmit={(fd) =>
                run(async () =>
                  createWorkspaceAuthorization(await getToken(), workspaceId, fd),
                )
              }
            />
          </div>
        </section>
      )}
    </div>
  );
}

function AuthForm({
  label,
  onSubmit,
}: {
  label: string;
  onSubmit: (fd: FormData) => Promise<void>;
}) {
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const fd = formData(e.currentTarget);
        e.currentTarget.reset();
        void onSubmit(fd);
      }}
    >
      <input name="signer_name" placeholder="Signer" required className="border p-1" />
      <input name="authorized_date" type="date" required className="border p-1" />
      <input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" />
      <button className="rounded bg-gray-800 px-2 py-1 text-white">{label}</button>
    </form>
  );
}
