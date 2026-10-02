import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EvidenceSection } from "./EvidenceSection";

// CLAUDE.md #7: the case view never renders captured imagery inline — evidence is opened via a
// signed URL in a new tab, never an <img>. This guards the staff side of the no-thumbnail rule.

vi.mock("@clerk/clerk-react", () => {
  const getToken = () => Promise.resolve("test-token");
  return { useAuth: () => ({ getToken }) };
});

vi.mock("../api", () => ({
  listEvidence: vi.fn(() =>
    Promise.resolve([
      {
        id: 1,
        kind: "screenshot",
        status: "sealed",
        timestamp_status: "ok",
        created_at: "2026-10-01T00:00:00Z",
        capture_finished_at: "2026-10-01T00:00:05Z",
        error: null,
      },
    ]),
  ),
  evidenceArtifactUrl: vi.fn(),
  evidencePackUrl: vi.fn(),
  recapture: vi.fn(),
  uploadEvidence: vi.fn(),
  verifyEvidence: vi.fn(),
}));

describe("EvidenceSection", () => {
  it("renders a sealed capture without any inline <img>", async () => {
    const { container } = render(
      <EvidenceSection workspaceId={1} caseId={1} isAdmin={true} />,
    );
    await screen.findByRole("button", { name: "manifest" });
    expect(container.querySelector("img")).toBeNull();
  });
});
