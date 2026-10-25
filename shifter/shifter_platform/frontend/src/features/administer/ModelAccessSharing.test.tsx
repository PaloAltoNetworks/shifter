import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

import { ModelAccessSharing } from "./ModelAccessSharing";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);

beforeEach(() => {
  api.mockReset();
});

describe("ModelAccessSharing", () => {
  it("previews matched ranges for the composed selector", async () => {
    api.mockResolvedValue({ matched: 3, members: [] });
    renderRoute(<ModelAccessSharing />);
    fireEvent.click(screen.getByRole("button", { name: "Preview matched ranges" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/model-access/bindings/selector-preview/", {
        method: "POST",
        body: { selector: { kind: "all_ranges", ids: [], include_spares: false } },
      }),
    );
    expect(await screen.findByText(/Matched 3 ranges/)).toBeInTheDocument();
  });

  it("publishes a composed binding and reports the new revision", async () => {
    api.mockResolvedValue({ sharing_binding_id: "b1", definition_revision: 1, state: "active" });
    renderRoute(<ModelAccessSharing />);
    fireEvent.change(screen.getByLabelText("Binding ID"), { target: { value: "b1" } });
    fireEvent.change(screen.getByLabelText("Pool ID"), { target: { value: "pool-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish binding" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/model-access/bindings/publish/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText(/is now active at revision 1/)).toBeInTheDocument();
  });

  it("shows a reload prompt on a stale definition revision (409)", async () => {
    api.mockRejectedValue(new ApiError(409, { code: "model_access_revision_conflict", message: "stale" }));
    renderRoute(<ModelAccessSharing />);
    fireEvent.change(screen.getByLabelText("Binding ID"), { target: { value: "b1" } });
    fireEvent.change(screen.getByLabelText("Pool ID"), { target: { value: "pool-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish binding" }));
    expect(await screen.findByText(/Reload this binding before saving/)).toBeInTheDocument();
  });

  it("validates a draft before publication", async () => {
    api.mockResolvedValue({ valid: true });
    renderRoute(<ModelAccessSharing />);
    fireEvent.change(screen.getByLabelText("Binding ID"), { target: { value: "b1" } });
    fireEvent.change(screen.getByLabelText("Pool ID"), { target: { value: "pool-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Validate draft" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/model-access/bindings/validate/", expect.objectContaining({ method: "POST" })),
    );
    expect(await screen.findByText("Draft is valid.")).toBeInTheDocument();
  });

  it("previews effective policy conflicts for a subject range", async () => {
    api.mockResolvedValue({
      stale: false,
      is_admissible: false,
      conflicts: [{ code: "priority_tie", facet: "spend", logical_alias: null }],
      contributions: [
        {
          sharing_binding_id: "b1",
          definition_digest: "sha256:x",
          membership_revision: 2,
          routing_revision: 1,
          priority: 5,
          matched_reason: "selected",
          facets: ["spend"],
        },
      ],
      alias_routings: [],
      account_summary: { capacity: 0, spend: 1, rate: 0, concurrency: 0 },
    });
    renderRoute(<ModelAccessSharing />);
    fireEvent.change(screen.getByLabelText("Range reference"), { target: { value: "range:abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview effective policy" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/model-access/bindings/policy-preview/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText(/Priority conflicts: priority_tie/)).toBeInTheDocument();
  });
});
