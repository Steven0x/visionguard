import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../App";

// CLAUDE.md #7: the agency portal must NEVER render imagery — not for ordinary cases and not
// for sensitive/ncii ones (whose display_url is domain-only). This guards against a future
// change that adds an <img> to the portal tree.

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
  // One ncii (sensitive) case with a domain-only display_url, one ordinary case.
  listPortalCases: vi.fn(() =>
    Promise.resolve([
      {
        id: 9,
        subject_id: 1,
        claim_type: "ncii",
        status: "filed",
        display_url: "https://leaks.example",
        created_at: "2026-10-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
      },
      {
        id: 10,
        subject_id: 1,
        claim_type: "copyright",
        status: "removed",
        display_url: "https://site.example/path",
        created_at: "2026-10-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
      },
    ]),
  ),
  getPortalCase: vi.fn(() =>
    Promise.resolve({
      case: {
        id: 9,
        subject_id: 1,
        claim_type: "ncii",
        status: "filed",
        display_url: "https://leaks.example",
        created_at: "2026-10-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
      },
      timeline: [{ from_status: null, to_status: "filed", created_at: "2026-10-01T00:00:00Z" }],
    }),
  ),
  listPortalSubjects: vi.fn(() => Promise.resolve([])),
  listPortalNeeds: vi.fn(() => Promise.resolve([])),
  listPortalReports: vi.fn(() => Promise.resolve([])),
  getPortalBilling: vi.fn(() =>
    Promise.resolve({
      billing_mode: "stripe",
      status: "active",
      plan_tier: "core",
      cadence: "monthly",
      quantity: 1,
      current_period_end: null,
      grace_until: null,
      in_grace: false,
      suspended: false,
      priority: false,
      has_subscription: true,
      is_billing_contact: false,
      billing_contact_email: null,
    }),
  ),
  listWorkspaces: vi.fn(() => Promise.resolve([])),
}));

describe("agency portal renders no imagery", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows no <img> in the case list or a sensitive case detail", async () => {
    const { container } = render(<App />);
    // Cases list (includes the ncii case).
    await screen.findByText("Case #9");
    expect(container.querySelector("img")).toBeNull();

    // Open the sensitive case detail.
    fireEvent.click(screen.getByRole("button", { name: "Case #9" }));
    await screen.findByRole("button", { name: /Back/ });
    expect(container.querySelector("img")).toBeNull();
  });
});
