import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunStatusBadge } from "./RunStatusBadge";

describe("RunStatusBadge", () => {
  it("styles a blocked run distinctly", () => {
    render(<RunStatusBadge status="blocked" />);
    const badge = screen.getByTestId("run-status");
    expect(badge).toHaveTextContent("blocked");
    expect(badge.className).toContain("text-red-700");
  });
});
