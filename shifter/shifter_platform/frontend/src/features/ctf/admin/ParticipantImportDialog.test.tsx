import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ParticipantImportDialog } from "./ParticipantImportDialog";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

describe("ParticipantImportDialog", () => {
  it("parses rows and posts them, then shows per-row errors", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({
      imported: 1,
      participants: [{ id: "p1", name: "Alice", email: "alice@example.com" }],
      errors: [{ index: 1, email: "taken@example.com", error: "Could not import participant." }],
    });
    renderRoute(<ParticipantImportDialog eventId="e1" />);
    await user.click(screen.getByRole("button", { name: "Import CSV" }));
    // Set the CSV in one change event rather than typing ~44 chars key-by-key:
    // per-keystroke re-renders amplify past the 5s testTimeout under full-suite
    // CPU contention (issue #1878). fireEvent.change is the repo's canonical way
    // to enter a field value; the component only reads the final textarea value.
    fireEvent.change(screen.getByLabelText("CSV rows"), {
      target: { value: "Alice,alice@example.com\nBob,taken@example.com" },
    });
    await user.click(screen.getByRole("button", { name: /Import 2 rows/ }));

    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/participants/import/",
      expect.objectContaining({
        method: "POST",
        body: {
          participants: [
            { name: "Alice", email: "alice@example.com" },
            { name: "Bob", email: "taken@example.com" },
          ],
        },
      }),
    );
    expect(await screen.findByText("1 imported.")).toBeInTheDocument();
    expect(screen.getByText(/Row 2: Could not import participant./)).toBeInTheDocument();
  });

  it("disables submit with no rows", async () => {
    const user = setupUser();
    renderRoute(<ParticipantImportDialog eventId="e1" />);
    await user.click(screen.getByRole("button", { name: "Import CSV" }));
    expect(screen.getByRole("button", { name: /Import\s+row/ })).toBeDisabled();
  });
});
