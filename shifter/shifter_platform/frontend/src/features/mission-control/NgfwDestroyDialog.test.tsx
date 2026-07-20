import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/errors";
import type { NGFWDestroyResponse, NGFWListItem } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { NgfwDestroyDialog } from "./NgfwDestroyDialog";

const mockApi = vi.mocked(apiFetch);

const NGFW: NGFWListItem = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "lab-ngfw",
  status: "ready",
  created_at: "2026-07-01T00:00:00Z",
  serial_number: "000000000000",
};

beforeEach(() => {
  mockApi.mockReset();
});

function renderDialog(props: Partial<React.ComponentProps<typeof NgfwDestroyDialog>> = {}) {
  const onOpenChange = vi.fn();
  const onDestroyed = vi.fn();
  const utils = renderRoute(
    <NgfwDestroyDialog ngfw={NGFW} open onOpenChange={onOpenChange} onDestroyed={onDestroyed} {...props} />,
  );
  return { ...utils, onOpenChange, onDestroyed };
}

describe("NgfwDestroyDialog", () => {
  it("keeps the confirm action disabled until the typed name matches exactly", async () => {
    const user = userEvent.setup();
    renderDialog();

    const confirmButton = screen.getByRole("button", { name: "Deprovision NGFW" });
    expect(confirmButton).toBeDisabled();

    await user.type(screen.getByLabelText(/Type/), "lab-ngf");
    expect(confirmButton).toBeDisabled();

    await user.type(screen.getByLabelText(/Type/), "w");
    expect(confirmButton).toBeEnabled();
  });

  it("destroys with the app id and typed confirm_name, then closes and notifies on success", async () => {
    mockApi.mockResolvedValue({ status: "deprovisioning" } satisfies NGFWDestroyResponse);
    const user = userEvent.setup();
    const { onOpenChange, onDestroyed } = renderDialog();

    await user.type(screen.getByLabelText(/Type/), "lab-ngfw");
    await user.click(screen.getByRole("button", { name: "Deprovision NGFW" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(`/mission-control/ngfw/${NGFW.id}/destroy/`, {
        method: "POST",
        body: { confirm_name: "lab-ngfw" },
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onDestroyed).toHaveBeenCalled();
  });

  it("shows a server error inline and does not retry automatically", async () => {
    mockApi.mockRejectedValue(new ApiError(409, { code: "conflict", message: "NGFW name did not match." }));
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    await user.type(screen.getByLabelText(/Type/), "lab-ngfw");
    await user.click(screen.getByRole("button", { name: "Deprovision NGFW" }));

    expect(await screen.findByText("NGFW name did not match.")).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
