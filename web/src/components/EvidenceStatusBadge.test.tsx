import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceStatusBadge } from "./EvidenceStatusBadge";

describe("EvidenceStatusBadge", () => {
  it("shows timestamped for a sealed+ok capture", () => {
    render(<EvidenceStatusBadge capture={{ status: "sealed", timestamp_status: "ok" }} />);
    expect(screen.getByTestId("evidence-status")).toHaveTextContent("sealed");
    expect(screen.getByText("timestamped")).toBeInTheDocument();
    expect(screen.queryByTestId("untimestamped")).toBeNull();
  });

  it("flags a sealed-but-untimestamped capture", () => {
    render(
      <EvidenceStatusBadge capture={{ status: "sealed", timestamp_status: "untimestamped" }} />,
    );
    expect(screen.getByTestId("untimestamped")).toHaveTextContent("untimestamped");
  });
});
