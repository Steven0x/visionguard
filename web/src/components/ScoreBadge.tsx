import type { InboxItem } from "../api";

/** Pure render of a candidate's score + a compact breakdown of why it scored that way. */
export function ScoreBadge({ item }: { item: InboxItem }) {
  const bd = item.score_breakdown;
  const chips: string[] = [];
  if (bd) {
    if (bd.phash.points > 0 && bd.phash.best_distance !== null) {
      chips.push(`pHash d=${bd.phash.best_distance}`);
    }
    if (bd.embedding.points > 0 && bd.embedding.best_similarity !== null) {
      chips.push(`similarity ${(bd.embedding.best_similarity * 100).toFixed(0)}%`);
    }
    if (bd.rules.leak_domain) chips.push("leak domain");
    for (const kw of bd.rules.risky_keywords) chips.push(`“${kw}”`);
  }

  return (
    <div className="space-y-1" data-testid="score-badge">
      <div className="flex items-center gap-2">
        <span className="rounded bg-gray-900 px-2 py-0.5 text-sm font-semibold text-white">
          {item.score ?? "—"}
        </span>
        {item.unverified && (
          <span className="text-xs text-amber-700" data-testid="unverified">
            unverified — needs manual check
          </span>
        )}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {chips.map((c) => (
            <span key={c} className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
