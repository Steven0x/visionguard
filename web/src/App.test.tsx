import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// Render Clerk's gates deterministically: signed in, with a fake session token. getToken is a
// STABLE reference (as real Clerk provides), so useToken() stays stable across renders.
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

vi.mock("./api", () => ({
  fetchMe: vi.fn(() =>
    Promise.resolve({
      id: 1,
      email: "staff@visionguard.test",
      role: "admin",
      all_workspaces: true,
      review_keep_blur: true,
    }),
  ),
  listWorkspaces: vi.fn(() => Promise.resolve([])),
  createWorkspace: vi.fn(),
}));

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the signed-in staff member and the workspaces console", async () => {
    render(<App />);
    expect(await screen.findByText("staff@visionguard.test")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Workspaces" })).toBeInTheDocument();
    // Brand wordmark is part of the app shell (rendered once me has loaded).
    expect(screen.getAllByText("VisionGuard").length).toBeGreaterThan(0);
  });

  it("fetches /me exactly once on mount (no render loop)", async () => {
    const api = await import("./api");
    render(<App />);
    await screen.findByRole("heading", { name: "Workspaces" });
    // Let any stray effects flush; a dependency-loop would fire many more /me calls.
    await new Promise((r) => setTimeout(r, 50));
    expect(api.fetchMe).toHaveBeenCalledTimes(1);
  });
});
