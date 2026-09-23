import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// Render Clerk's gates deterministically: signed in, with a fake session token.
vi.mock("@clerk/clerk-react", () => ({
  SignedIn: ({ children }: { children: ReactNode }) => <>{children}</>,
  SignedOut: () => null,
  SignInButton: () => <button>Sign in</button>,
  UserButton: () => <div data-testid="user-button" />,
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

vi.mock("./api", () => ({
  fetchMe: vi.fn(() =>
    Promise.resolve({
      id: 1,
      email: "staff@visionguard.test",
      role: "admin",
      all_workspaces: true,
    }),
  ),
}));

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the signed-in staff member from GET /me", async () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "VisionGuard" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("staff@visionguard.test")).toBeInTheDocument();
    expect(screen.getByText(/role: admin/)).toBeInTheDocument();
  });
});
