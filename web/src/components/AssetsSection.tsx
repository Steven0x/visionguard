import { useCallback, useEffect, useState } from "react";
import {
  type Asset,
  assetThumbnailUrl,
  deleteAsset,
  listAssets,
  retryAsset,
  uploadAsset,
} from "../api";
import { useToken } from "../useToken";
import { AssetStatusBadge } from "./AssetStatusBadge";

function Thumbnail({
  workspaceId,
  subjectId,
  asset,
}: {
  workspaceId: number;
  subjectId: number;
  asset: Asset;
}) {
  const getToken = useToken();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const res = await assetThumbnailUrl(await getToken(), workspaceId, subjectId, asset.id);
        if (active) setUrl(res.url);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken, workspaceId, subjectId, asset.id]);

  if (!url) return <div className="h-20 w-20 rounded bg-gray-100" />;
  return <img src={url} alt={asset.file_name} className="h-20 w-20 rounded object-cover" />;
}

export function AssetsSection({
  workspaceId,
  subjectId,
}: {
  workspaceId: number;
  subjectId: number;
}) {
  const getToken = useToken();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setAssets(await listAssets(await getToken(), workspaceId, subjectId));
    } catch (e) {
      setError(String(e));
    }
  }, [getToken, workspaceId, subjectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Poll while anything is still being fingerprinted.
  useEffect(() => {
    if (!assets.some((a) => a.status === "pending" || a.status === "processing")) return;
    const timer = setInterval(() => void reload(), 2500);
    return () => clearInterval(timer);
  }, [assets, reload]);

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
    <section className="space-y-2">
      <h3 className="font-medium">Reference images</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex flex-wrap gap-3">
        {assets.map((a) => (
          <div key={a.id} className="w-24 space-y-1 text-xs">
            <Thumbnail workspaceId={workspaceId} subjectId={subjectId} asset={a} />
            <div className="flex items-center gap-1">
              <AssetStatusBadge status={a.status} />
              {a.duplicate_of_asset_id && <span className="text-amber-700">dup</span>}
            </div>
            <div className="flex gap-2">
              {a.status === "failed" && (
                <button
                  className="text-blue-700"
                  onClick={() =>
                    act(async () => retryAsset(await getToken(), workspaceId, subjectId, a.id))
                  }
                >
                  retry
                </button>
              )}
              <button
                className="text-red-700"
                onClick={() =>
                  act(async () => deleteAsset(await getToken(), workspaceId, subjectId, a.id))
                }
              >
                delete
              </button>
            </div>
          </div>
        ))}
      </div>
      <input
        type="file"
        accept=".jpg,.jpeg,.png,.webp"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.currentTarget.value = "";
          if (file) void act(async () => uploadAsset(await getToken(), workspaceId, subjectId, file));
        }}
      />
    </section>
  );
}
