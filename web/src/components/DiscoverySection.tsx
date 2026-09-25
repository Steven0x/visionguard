import { useCallback, useEffect, useState } from "react";
import {
  type DiscoveryCandidate,
  type DiscoveryRun,
  candidateThumbnailUrl,
  intakeUrls,
  listDiscoveryCandidates,
  listDiscoveryRuns,
  scanNow,
} from "../api";
import { useToken } from "../useToken";
import { RunStatusBadge } from "./RunStatusBadge";

function CandidateThumb({
  workspaceId,
  subjectId,
  candidate,
}: {
  workspaceId: number;
  subjectId: number;
  candidate: DiscoveryCandidate;
}) {
  const getToken = useToken();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!candidate.has_thumbnail) return;
    let active = true;
    void (async () => {
      try {
        const r = await candidateThumbnailUrl(await getToken(), workspaceId, subjectId, candidate.id);
        if (active) setUrl(r.url);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken, workspaceId, subjectId, candidate.id, candidate.has_thumbnail]);

  if (!candidate.has_thumbnail) {
    return (
      <div className="flex h-16 w-16 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-500">
        link
      </div>
    );
  }
  if (!url) return <div className="h-16 w-16 rounded bg-gray-100" />;
  return <img src={url} alt="candidate" className="h-16 w-16 rounded object-cover" />;
}

export function DiscoverySection({
  workspaceId,
  subjectId,
}: {
  workspaceId: number;
  subjectId: number;
}) {
  const getToken = useToken();
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [urls, setUrls] = useState("");

  const reload = useCallback(async () => {
    try {
      const t = await getToken();
      setCandidates(await listDiscoveryCandidates(t, workspaceId, subjectId));
      setRuns(await listDiscoveryRuns(t, workspaceId, subjectId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, subjectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!runs.some((r) => r.status === "running")) return;
    const timer = setInterval(() => void reload(), 2000);
    return () => clearInterval(timer);
  }, [runs, reload]);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <section className="space-y-3">
      <h3 className="font-medium">Discovery</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        className="rounded bg-blue-700 px-2 py-1 text-sm text-white"
        onClick={() => act(async () => scanNow(await getToken(), workspaceId, subjectId))}
      >
        Scan now
      </button>

      <form
        className="space-y-1"
        onSubmit={(e) => {
          e.preventDefault();
          const list = urls.split(/\s+/).map((s) => s.trim()).filter(Boolean);
          setUrls("");
          if (list.length) {
            void act(async () => intakeUrls(await getToken(), workspaceId, subjectId, list));
          }
        }}
      >
        <textarea
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
          placeholder="Paste found URLs (whitespace-separated, max 200)"
          rows={3}
          className="w-full border p-1 text-sm"
        />
        <button className="rounded bg-gray-800 px-2 py-1 text-sm text-white">Add URLs</button>
      </form>

      <div>
        <h4 className="text-sm font-medium">Recent runs</h4>
        <ul className="space-y-1 text-xs">
          {runs.slice(0, 5).map((r) => (
            <li key={r.id} className="flex items-center gap-2">
              <RunStatusBadge status={r.status} />
              <span>{r.kind}</span>
              <span className="text-gray-400">
                {r.calls_made} calls · {r.candidates_found} found · {r.estimated_cost_cents}¢
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h4 className="text-sm font-medium">Candidates ({candidates.length})</h4>
        <div className="flex flex-wrap gap-3">
          {candidates.map((c) => (
            <div key={c.id} className="w-40 space-y-1 text-xs">
              <CandidateThumb workspaceId={workspaceId} subjectId={subjectId} candidate={c} />
              <div className="text-gray-500">
                {c.provider} · {c.kind}
              </div>
              <a
                href={c.page_url ?? c.source_url}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-blue-700"
              >
                {c.page_url ?? c.source_url}
              </a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
