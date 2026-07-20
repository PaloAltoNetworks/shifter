import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Bootstrap } from "@/api/types";
import { STAFF_BOOTSTRAP } from "@/test/utils";

import { ModeProvider, useMode } from "./mode";

function withModes(modes: Bootstrap["modes"]): Bootstrap {
  return { ...STAFF_BOOTSTRAP, modes };
}

function Probe() {
  const { mode, canSwitch, setMode } = useMode();
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="can-switch">{String(canSwitch)}</span>
      <button type="button" onClick={() => setMode("participant")}>
        to-participant
      </button>
    </div>
  );
}

function renderWith(modes: Bootstrap["modes"]) {
  return render(
    <ModeProvider bootstrap={withModes(modes)}>
      <Probe />
    </ModeProvider>,
  );
}

describe("ModeProvider", () => {
  it("starts on the server-provided default mode", () => {
    renderWith({ participant: true, operator: true, default: "operator" });
    expect(screen.getByTestId("mode")).toHaveTextContent("operator");
    expect(screen.getByTestId("can-switch")).toHaveTextContent("true");
  });

  it("cannot switch when only one mode is eligible", () => {
    renderWith({ participant: false, operator: true, default: "operator" });
    expect(screen.getByTestId("can-switch")).toHaveTextContent("false");
  });

  it("ignores a switch into an ineligible mode", async () => {
    renderWith({ participant: false, operator: true, default: "operator" });
    await userEvent.click(screen.getByRole("button", { name: "to-participant" }));
    expect(screen.getByTestId("mode")).toHaveTextContent("operator");
  });

  it("switches into an eligible mode", async () => {
    renderWith({ participant: true, operator: true, default: "operator" });
    await userEvent.click(screen.getByRole("button", { name: "to-participant" }));
    expect(screen.getByTestId("mode")).toHaveTextContent("participant");
  });

  it("falls back to an eligible mode when the default is not eligible", () => {
    renderWith({ participant: true, operator: false, default: "operator" });
    expect(screen.getByTestId("mode")).toHaveTextContent("participant");
  });
});
