import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { ReviewInbox } from "./ReviewInbox";

// getToken must be a STABLE reference (as real Clerk provides) — a fresh function each render
// makes useToken unstable and reload-loops the inbox. See useToken.ts.
vi.mock("@clerk/clerk-react", () => {
  const getToken = () => Promise.resolve("test-token");
  return { useAuth: () => ({ getToken }) };
});

const ITEM = {
  id: 42,
  subject_name: "Demo Subject",
  provider: "google_lens",
  score: 80,
  supported_claims: ["likeness"],
  suggested_claim: "likeness",
  page_url: "https://leaks.example/x",
  source_url: "https://leaks.example/x",
  unverified: false,
  score_breakdown: null,
};

vi.mock("../api", () => ({
  DISMISS_REASONS: ["not_a_match", "allowlisted", "other"],
  listInbox: vi.fn(() => Promise.resolve([ITEM])),
  confirmCandidate: vi.fn(() => Promise.resolve({})),
  dismissCandidate: vi.fn(() => Promise.resolve({})),
  foundThumbnailUrl: vi.fn(() => Promise.resolve({ url: "blob:found" })),
  assetMatchThumbnailUrl: vi.fn(() => Promise.resolve({ url: "blob:asset" })),
  updateReviewPrefs: vi.fn(() => Promise.resolve({})),
  bulkDismiss: vi.fn(() => Promise.resolve({ count: 0 })),
  reopenCandidate: vi.fn(() => Promise.resolve({})),
}));

function renderInbox() {
  return render(<ReviewInbox workspaceId={1} isAdmin={false} keepBlurDefault={true} />);
}

describe("ReviewInbox", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the found thumbnail blurred until revealed (CLAUDE.md #7)", async () => {
    renderInbox();
    const found = await screen.findByTestId("thumb-found");
    expect(found.className).toContain("blur-lg");
    // The subject's own asset thumbnail is never blurred.
    expect(screen.getByTestId("thumb-asset").className).not.toContain("blur-lg");
  });

  it("confirms the selected candidate with the C key", async () => {
    renderInbox();
    await screen.findByText("Demo Subject");
    fireEvent.keyDown(screen.getByTestId("review-inbox"), { key: "c" });
    await waitFor(() =>
      expect(vi.mocked(api.confirmCandidate)).toHaveBeenCalledWith("test-token", 1, 42, "likeness"),
    );
  });

  it("dismisses the selected candidate with the D key", async () => {
    renderInbox();
    await screen.findByText("Demo Subject");
    fireEvent.keyDown(screen.getByTestId("review-inbox"), { key: "d" });
    await waitFor(() =>
      expect(vi.mocked(api.dismissCandidate)).toHaveBeenCalledWith(
        "test-token",
        1,
        42,
        "not_a_match",
      ),
    );
  });
});
