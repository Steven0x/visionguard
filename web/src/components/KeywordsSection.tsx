import { useCallback, useEffect, useState } from "react";
import { type Keyword, addKeyword, listKeywords, removeKeyword } from "../api";
import { useToken } from "../useToken";

export function KeywordsSection({
  workspaceId,
  subjectId,
}: {
  workspaceId: number;
  subjectId: number;
}) {
  const getToken = useToken();
  const [keywords, setKeywords] = useState<Keyword[]>([]);

  const reload = useCallback(async () => {
    setKeywords(await listKeywords(await getToken(), workspaceId, subjectId));
  }, [getToken, workspaceId, subjectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <section className="space-y-2">
      <h3 className="font-medium">Keywords</h3>
      <ul className="flex flex-wrap gap-2 text-sm">
        {keywords.map((k) => (
          <li key={k.id} className="rounded bg-gray-100 px-2 py-0.5">
            {k.keyword}{" "}
            <button
              className="text-red-700"
              onClick={async () => {
                await removeKeyword(await getToken(), workspaceId, subjectId, k.id);
                await reload();
              }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          const keyword = String(form.get("keyword") ?? "").trim();
          e.currentTarget.reset();
          if (keyword) {
            await addKeyword(await getToken(), workspaceId, subjectId, keyword);
            await reload();
          }
        }}
      >
        <input name="keyword" placeholder="e.g. stage name + leaked" className="border p-1" />
        <button className="rounded bg-blue-700 px-2 py-1 text-white">Add</button>
      </form>
    </section>
  );
}
