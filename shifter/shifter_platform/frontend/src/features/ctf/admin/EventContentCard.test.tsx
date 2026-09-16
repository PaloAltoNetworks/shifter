import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import type { CtfEventDetail } from "@/api/types";
import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventContentCard } from "./EventContentCard";

const mockApi = vi.mocked(apiFetch);
const DIGEST = `sha256:${"a".repeat(64)}`;

function managedEvent(overrides: Record<string, unknown> = {}): CtfEventDetail {
  return {
    id: "e1",
    managed_content: {
      scenario_id: "basic",
      declared_digest: DIGEST,
      state: "drifted",
      is_refreshable: true,
      ...overrides,
    },
  } as unknown as CtfEventDetail;
}

beforeEach(() => mockApi.mockReset());

describe("EventContentCard", () => {
  it("renders nothing for an unmanaged event", () => {
    const { container } = renderRoute(
      <EventContentCard event={{ id: "e1", managed_content: null } as unknown as CtfEventDetail} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("refreshes to the configured revision using the current digest as the fence", async () => {
    mockApi.mockResolvedValue({ outcome: "refreshed" });
    const user = setupUser();
    renderRoute(<EventContentCard event={managedEvent()} />);

    await user.click(screen.getByRole("button", { name: "Refresh to configured revision" }));
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/content/refresh/",
      expect.objectContaining({ method: "POST", body: { expected_current_digest: DIGEST } }),
    );
    expect(await screen.findByText("Content refreshed")).toBeInTheDocument();
  });

  it("disables refresh for a non-refreshable (ended/archived) event", () => {
    renderRoute(<EventContentCard event={managedEvent({ is_refreshable: false })} />);
    expect(screen.getByRole("button", { name: "Refresh to configured revision" })).toBeDisabled();
  });
});
