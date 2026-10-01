import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../App";

vi.mock("@clerk/clerk-react", () => {
  const getToken = () => Promise.resolve("test-token");
  return {
    SignedIn: ({ children }: { children: ReactNode }) => <>{children}</>,
    SignedOut: () => null,
    SignInButton: () => <button>Sign in</button>,
    UserButton: () => <div data-testid="user-button" />,
    useAuth: () => ({ getToken }),
  };
});

// An agency user; the portal calls getPortalContext + the per-tab loaders.
vi.mock("../../api", () => ({
  fetchMe: vi.fn(() =>
    Promise.resolve({
      id: 7,
      email: "agency@client.test",
      role: "agency",
      all_workspaces: false,
      review_keep_blur: true,
    }),
  ),
  getPortalContext: vi.fn(() =>
    Promise.resolve({
      email: "agency@client.test",
      role: "agency",
      workspace_id: 3,
      workspace_name: "Acme Talent",
    }),
  ),
  listPortalCases: vi.fn(() =>
    Promise.resolve([
      {
        id: 1,
        subject_id: 1,
        claim_type: "copyright",
        status: "filed",
        display_url: "https://site.example",
        created_at: "2026-10-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
      },
    ]),
  ),
  // Staff-console functions must NOT be called for an agency user.
  listWorkspaces: vi.fn(() => Promise.resolve([])),
}));

describe("AgencyPortal routing", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the portal for an agency user and not the staff console", async () => {
    render(<App />);
    expect(await screen.findByText("Acme Talent — signed in as agency@client.test")).toBeInTheDocument();
    // Portal chrome is present…
    expect(screen.getByRole("button", { name: "Needs from you" })).toBeInTheDocument();
    // …and the staff console ("Workspaces") is not.
    expect(screen.queryByRole("heading", { name: "Workspaces" })).not.toBeInTheDocument();
    const api = await import("../../api");
    expect(api.listWorkspaces).not.toHaveBeenCalled();
  });

  it("shows a minimized case row (status + domain url, no internal fields)", async () => {
    render(<App />);
    expect(await screen.findByText("Case #1")).toBeInTheDocument();
    expect(screen.getByText("https://site.example")).toBeInTheDocument();
  });
});
