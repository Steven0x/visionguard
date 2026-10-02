import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CaseStatus } from "../../api";
import { STATUS_TONE, StatusBadge } from "./StatusBadge";

const ALL: CaseStatus[] = [
  "discovered",
  "confirmed",
  "dismissed",
  "filed",
  "removed",
  "countered",
  "escalated",
  "withdrawn",
  "monitoring",
  "recovered",
  "closed",
];

describe("StatusBadge", () => {
  it("has a tone for every case status (single source of truth)", () => {
    for (const s of ALL) {
      expect(STATUS_TONE[s]).toBeTruthy();
    }
  });

  it("renders each status label", () => {
    for (const s of ALL) {
      const { unmount } = render(<StatusBadge status={s} />);
      expect(screen.getByTestId("case-status")).toHaveTextContent(s);
      unmount();
    }
  });

  it("shows an overdue marker only when overdue", () => {
    const { rerender } = render(<StatusBadge status="filed" />);
    expect(screen.queryByTestId("overdue")).toBeNull();
    rerender(<StatusBadge status="filed" overdue />);
    expect(screen.getByTestId("overdue")).toHaveTextContent("overdue");
  });
});
