import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PreviewRow } from "../api";
import { ImportPreviewTable } from "./ImportPreviewTable";

describe("ImportPreviewTable", () => {
  it("renders per-row validation errors", () => {
    const rows: PreviewRow[] = [
      { row_no: 1, values: { legal_name: "", handles: [] }, errors: ["legal_name is required"] },
      {
        row_no: 2,
        values: { legal_name: "Jane Doe", handles: ["ig:jane"], residence_state: "CA" },
        errors: [],
      },
    ];
    render(<ImportPreviewTable rows={rows} />);

    expect(screen.getByText("legal_name is required")).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("ig:jane")).toBeInTheDocument();
    // The erroring row is highlighted.
    expect(screen.getByTestId("row-1").className).toContain("bg-red-50");
    expect(screen.getByTestId("row-2").className).not.toContain("bg-red-50");
  });
});
