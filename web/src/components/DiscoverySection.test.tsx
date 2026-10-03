import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DiscoverySection } from "./DiscoverySection";

vi.mock("@clerk/clerk-react", () => {
  const getToken = () => Promise.resolve("test-token");
  return { useAuth: () => ({ getToken }) };
});

const FAILED_RUN = {
  id: 1,
  kind: "keyword",
  provider: "google_search",
  status: "failed" as const,
  calls_made: 0,
  estimated_cost_cents: 0,
  candidates_found: 0,
  error: "SerpApi: Invalid API key, please check your SerpApi account.",
  started_at: "2026-10-03T00:00:00Z",
  finished_at: "2026-10-03T00:00:01Z",
};

vi.mock("../api", () => ({
  listDiscoveryRuns: vi.fn(() => Promise.resolve([FAILED_RUN])),
  listDiscoveryCandidates: vi.fn(() => Promise.resolve([])),
  getDiscoverySettings: vi.fn(() => Promise.resolve({ safe_mode: false })),
  intakeUrls: vi.fn(),
  scanNow: vi.fn(),
  candidateThumbnailUrl: vi.fn(() => Promise.resolve({ url: "blob:x" })),
}));

describe("DiscoverySection", () => {
  it("shows the failure reason on a failed run, not just the status", async () => {
    render(<DiscoverySection workspaceId={1} subjectId={2} />);
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("failed"));
    expect(screen.getByTestId("run-error")).toHaveTextContent(
      "SerpApi: Invalid API key, please check your SerpApi account.",
    );
  });
});
