import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CaseStatusBadge } from "./CaseStatusBadge";

describe("CaseStatusBadge", () => {
  it("renders the status", () => {
    render(<CaseStatusBadge row={{ status: "filed", overdue: false }} />);
    expect(screen.getByTestId("case-status")).toHaveTextContent("filed");
    expect(screen.queryByTestId("overdue")).toBeNull();
  });

  it("marks overdue cases", () => {
    render(<CaseStatusBadge row={{ status: "filed", overdue: true }} />);
    expect(screen.getByTestId("overdue")).toHaveTextContent("overdue");
  });
});
