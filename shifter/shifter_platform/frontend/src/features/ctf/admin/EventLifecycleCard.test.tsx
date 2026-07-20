import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import type { CtfEventDetail } from "@/api/types";

import { EventLifecycleCard } from "./EventLifecycleCard";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

const EVENT = { id: "e1", name: "Spring CTF", status: "active" } as unknown as CtfEventDetail;

describe("EventLifecycleCard", () => {
  it("offers status-appropriate transitions", () => {
    renderRoute(<EventLifecycleCard event={EVENT} />);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End event" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel event" })).toBeInTheDocument();

    renderRoute(<EventLifecycleCard event={{ ...EVENT, status: "draft" }} />);
    expect(screen.getByRole("button", { name: "Open registration" })).toBeInTheDocument();
  });

  it("posts the transition", async () => {
    mockApi.mockResolvedValue({ id: "e1", name: "Spring CTF", status: "paused" });
    renderRoute(<EventLifecycleCard event={EVENT} />);
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/lifecycle/",
      expect.objectContaining({ method: "POST", body: { action: "pause" } }),
    );
  });

  it("cancel requires confirmation", async () => {
    mockApi.mockResolvedValue({ id: "e1", name: "Spring CTF", status: "cancelled" });
    renderRoute(<EventLifecycleCard event={EVENT} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    expect(mockApi).not.toHaveBeenCalled();
    // The dialog's confirm button shares the label; the API call proves the confirm path ran.
    await userEvent.click(await screen.findByRole("button", { name: "Cancel event" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/lifecycle/",
      expect.objectContaining({ method: "POST", body: { action: "cancel" } }),
    );
  });

  it("renders nothing for terminal states", () => {
    const { container } = renderRoute(<EventLifecycleCard event={{ ...EVENT, status: "ended" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
