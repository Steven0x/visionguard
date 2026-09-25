import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AssetStatusBadge } from "./AssetStatusBadge";

describe("AssetStatusBadge", () => {
  it("renders the status label with a status-specific style", () => {
    render(<AssetStatusBadge status="failed" />);
    const badge = screen.getByTestId("asset-status");
    expect(badge).toHaveTextContent("failed");
    expect(badge.className).toContain("text-red-700");
  });
});
