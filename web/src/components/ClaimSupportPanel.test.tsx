import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ClaimSupportResponse } from "../api";
import { ClaimSupportPanel } from "./ClaimSupportPanel";

const data: ClaimSupportResponse = {
  matrix_status: "draft — pending counsel",
  claims: [
    { claim_type: "copyright", supported: true, missing: [] },
    { claim_type: "trademark", supported: false, missing: ["trademark registration record"] },
  ],
  enforcement: { enforceable: true, active_authorization_id: 7 },
  biometrics: {
    active_biometric_consent: false,
    biometrics_blocked: false,
    biometric_features_enabled: false,
  },
};

describe("ClaimSupportPanel", () => {
  it("shows the draft label, per-claim status, and the biometrics disclaimer", () => {
    render(<ClaimSupportPanel data={data} />);
    expect(screen.getByText(/draft — pending counsel/)).toBeInTheDocument();
    expect(screen.getByTestId("claim-copyright")).toHaveTextContent("supported");
    expect(screen.getByTestId("claim-trademark")).toHaveTextContent("unsupported");
    expect(
      screen.getByText(/never implies biometric consent/),
    ).toBeInTheDocument();
  });
});
