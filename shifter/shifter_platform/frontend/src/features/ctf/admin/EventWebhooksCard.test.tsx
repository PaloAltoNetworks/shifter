import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventWebhooksCard } from "./EventWebhooksCard";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

describe("EventWebhooksCard", () => {
  it("lists webhooks with delivery status and removes them", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({
      webhooks: [
        {
          id: "w1",
          url: "https://hooks.example.test/ctf",
          subscribed_events: [],
          active: true,
          has_secret: true,
          last_status: "ok:200",
          last_delivery_at: null,
        },
      ],
    });
    renderRoute(<EventWebhooksCard eventId="e1" />);
    expect(await screen.findByText("https://hooks.example.test/ctf")).toBeInTheDocument();
    expect(screen.getByText("ok:200")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(mockApi).toHaveBeenCalledWith("/ctf/webhooks/w1/", expect.objectContaining({ method: "DELETE" }));
  });

  it("registers a webhook with a secret", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue({ webhooks: [] });
    renderRoute(<EventWebhooksCard eventId="e1" />);
    await screen.findByText("No webhooks registered.");
    await user.type(screen.getByLabelText("Endpoint URL"), "https://hooks.example.test/x");
    await user.type(screen.getByLabelText("Secret (optional)"), "shh");
    await user.click(screen.getByRole("button", { name: "Add webhook" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/webhooks/",
      expect.objectContaining({ method: "POST", body: { url: "https://hooks.example.test/x", secret: "shh" } }),
    );
  });
});
