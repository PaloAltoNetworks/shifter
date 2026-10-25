import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

import { ModelSourceForm } from "./ModelSourceForm";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);
beforeEach(() => { api.mockReset(); });

it("sends an explicit source choice and clears the transient credential after failure", async () => {
  api.mockRejectedValue(new ApiError(400, { code: "source_invalid", message: "Credential could not be stored" }));
  renderRoute(<ModelSourceForm organization="org-1" onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Workshop" } });
  fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "anthropic-v1" } });
  fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "claude-synthetic-20260901" } });
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: "synthetic-key" } });
  fireEvent.change(screen.getByLabelText("Quota account identity"), { target: { value: "account:workshop" } });
  fireEvent.change(screen.getByLabelText("Input price per million tokens (micro-units)"), { target: { value: "1000000" } });
  fireEvent.change(screen.getByLabelText("Output price per million tokens (micro-units)"), { target: { value: "3000000" } });
  fireEvent.change(screen.getByLabelText("Price valid until"), { target: { value: "2027-10-01" } });
  fireEvent.click(screen.getByLabelText("Allow organization members to use this source"));
  fireEvent.submit(screen.getByRole("form", { name: "Model source" }));
  expect(await screen.findByText("Credential could not be stored")).toBeInTheDocument();
  expect(screen.getByLabelText("API key")).toHaveValue("");
  await waitFor(() => expect(api).toHaveBeenCalledWith("/cms/organizations/org-1/model-sources/", expect.objectContaining({
    method: "POST", body: expect.objectContaining({ configuration: expect.objectContaining({
      provider: "anthropic-v1", allow_organization_members: true,
    }), credential: { api_key: "synthetic-key" } }),
  })));
  expect(api).toHaveBeenCalledTimes(1);
});

it("offers platform and external project placement without imposing a separate project", () => {
  renderRoute(<ModelSourceForm organization="org-1" onSaved={vi.fn()} />);
  expect(screen.getByLabelText("Google Cloud project")).toBeInTheDocument();
  expect(screen.getByText(/You may use the project hosting Shifter/)).toBeInTheDocument();
  expect(screen.getByLabelText("Allow organization members to use this source")).not.toBeChecked();
});
