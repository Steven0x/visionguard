import { useState } from "react";
import { commitImport, previewImport, type PreviewResponse } from "../api";
import { useToken } from "../useToken";
import { ImportPreviewTable } from "./ImportPreviewTable";

export function SubjectImport({
  workspaceId,
  onImported,
}: {
  workspaceId: number;
  onImported: () => void;
}) {
  const getToken = useToken();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const doPreview = async () => {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      setPreview(await previewImport(await getToken(), workspaceId, file));
    } catch (e) {
      setError(String(e));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const doCommit = async () => {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const result = await commitImport(await getToken(), workspaceId, file);
      setPreview(null);
      setFile(null);
      onImported();
      window.alert(`Imported ${result.imported} subjects`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 rounded border border-gray-200 p-3">
      <h4 className="font-medium">CSV import</h4>
      <p className="text-xs text-gray-500">
        Columns: legal_name, stage_names, handles, residence_state, notes
        (stage_names/handles are ;-separated).
      </p>
      <div className="flex items-center gap-2">
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPreview(null);
          }}
        />
        <button
          className="rounded bg-gray-800 px-2 py-1 text-sm text-white disabled:opacity-40"
          disabled={!file || busy}
          onClick={doPreview}
        >
          Preview
        </button>
        <button
          className="rounded bg-green-700 px-2 py-1 text-sm text-white disabled:opacity-40"
          disabled={!preview || preview.has_errors || busy}
          onClick={doCommit}
        >
          Commit
        </button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {preview && (
        <>
          {preview.has_errors && (
            <p className="text-sm text-red-600">
              Fix the highlighted rows before committing.
            </p>
          )}
          <ImportPreviewTable rows={preview.rows} />
        </>
      )}
    </div>
  );
}
