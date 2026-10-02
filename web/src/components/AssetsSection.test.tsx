import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { AssetsSection } from "./AssetsSection";

vi.mock("@clerk/clerk-react", () => {
  const getToken = () => Promise.resolve("test-token");
  return { useAuth: () => ({ getToken }) };
});

vi.mock("../api", () => ({
  listAssets: vi.fn(),
  assetThumbnailUrl: vi.fn(() => Promise.resolve({ url: "blob:thumb" })),
  deleteAsset: vi.fn(),
  retryAsset: vi.fn(),
  uploadAsset: vi.fn(),
}));

const asset = (over: Partial<api.Asset>): api.Asset => ({
  id: 1,
  subject_id: 1,
  file_name: "a.png",
  content_type: "image/png",
  size_bytes: 1,
  status: "ready",
  sha256: "x",
  phash: "y",
  has_embedding: false,
  duplicate_of_asset_id: null,
  error: null,
  attempts: 0,
  ...over,
});

describe("AssetsSection biometric label", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows exact-match-only when a ready asset has no embedding", async () => {
    vi.mocked(api.listAssets).mockResolvedValue([asset({ has_embedding: false })]);
    render(<AssetsSection workspaceId={1} subjectId={1} />);
    expect(await screen.findByTestId("exact-match-only")).toHaveTextContent(
      "exact-match only — no biometric consent",
    );
  });

  it("hides the label when the asset has a biometric embedding", async () => {
    vi.mocked(api.listAssets).mockResolvedValue([asset({ has_embedding: true })]);
    render(<AssetsSection workspaceId={1} subjectId={1} />);
    await screen.findByText("Reference images");
    expect(screen.queryByTestId("exact-match-only")).toBeNull();
  });
});
