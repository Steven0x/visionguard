import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { InboxItem, ScoreBreakdown } from "../api";
import { ScoreBadge } from "./ScoreBadge";

function item(overrides: Partial<InboxItem>, bd: Partial<ScoreBreakdown>): InboxItem {
  return {
    id: 1,
    subject_id: 1,
    subject_name: "Subj",
    provider: "fake",
    kind: "image",
    source_url: "https://x.example/1.jpg",
    page_url: null,
    score: 72,
    best_match_asset_id: 5,
    has_found_thumbnail: true,
    has_asset_thumbnail: true,
    unverified: false,
    suggested_claim: "likeness",
    supported_claims: ["likeness"],
    discovered_at: "2026-09-24T00:00:00Z",
    score_breakdown: {
      phash: { best_distance: 2, asset_id: 5, points: 60 },
      embedding: { best_similarity: 0.91, asset_id: 5, points: 36 },
      rules: { leak_domain: true, risky_keywords: ["leaked"], points: 33 },
      visual_points: 60,
      unverified: false,
      ...bd,
    },
    ...overrides,
  };
}

describe("ScoreBadge", () => {
  it("shows the score and a breakdown of the matched signals", () => {
    render(<ScoreBadge item={item({}, {})} />);
    expect(screen.getByTestId("score-badge")).toHaveTextContent("72");
    expect(screen.getByText("pHash d=2")).toBeInTheDocument();
    expect(screen.getByText("similarity 91%")).toBeInTheDocument();
    expect(screen.getByText("leak domain")).toBeInTheDocument();
    expect(screen.getByText("“leaked”")).toBeInTheDocument();
    expect(screen.queryByTestId("unverified")).toBeNull();
  });

  it("labels unverified link candidates", () => {
    render(
      <ScoreBadge
        item={item(
          { kind: "link", unverified: true, has_found_thumbnail: false },
          { unverified: true, phash: { best_distance: null, asset_id: null, points: 0 } },
        )}
      />,
    );
    expect(screen.getByTestId("unverified")).toHaveTextContent("needs manual check");
    expect(screen.queryByText(/pHash/)).toBeNull();
  });
});
