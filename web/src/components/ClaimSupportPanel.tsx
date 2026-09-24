import type { ClaimSupportResponse } from "../api";

/** Pure render of the derived claim-support + enforcement + biometric status. */
export function ClaimSupportPanel({ data }: { data: ClaimSupportResponse }) {
  const bio = data.biometrics;
  return (
    <section className="space-y-3 rounded border border-gray-200 p-3">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Supported claim types</h3>
        <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
          claims matrix: {data.matrix_status}
        </span>
      </div>

      <p className="text-sm">
        Enforceable:{" "}
        {data.enforcement.enforceable ? (
          <span className="text-green-700">yes</span>
        ) : (
          <span className="text-red-700">no — needs an active agent authorization</span>
        )}
      </p>

      <ul className="space-y-1 text-sm">
        {data.claims.map((c) => (
          <li key={c.claim_type} data-testid={`claim-${c.claim_type}`}>
            <span className="font-mono">{c.claim_type}</span>:{" "}
            {c.supported ? (
              <span className="text-green-700">supported</span>
            ) : (
              <span className="text-gray-600">
                unsupported — needs {c.missing.join("; ")}
              </span>
            )}
          </li>
        ))}
      </ul>

      <div className="rounded bg-gray-50 p-2 text-xs text-gray-600">
        <p>
          Biometric features:{" "}
          {bio.biometric_features_enabled ? (
            <span className="text-green-700">enabled</span>
          ) : (
            <span className="text-gray-700">disabled</span>
          )}{" "}
          (active biometric consent: {bio.active_biometric_consent ? "yes" : "no"};
          biometrics_blocked: {bio.biometrics_blocked ? "yes" : "no"})
        </p>
        <p className="mt-1">
          Note: <strong>biometrics_blocked = false never implies biometric consent.</strong>{" "}
          Biometric features require an active biometric consent record AND
          biometrics_blocked = false.
        </p>
      </div>
    </section>
  );
}
