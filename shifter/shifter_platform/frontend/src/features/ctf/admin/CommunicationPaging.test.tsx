import { afterEach, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoute } from "@/test/utils";
import { MonitoringPage } from "./MonitoringPage";

afterEach(() => vi.unstubAllGlobals());

it("loads and cancels a campaign after the first 25 records", async () => {
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    let body: unknown = {};
    if (url === "/api/v1/ctf/events/e1/") body = { workspace: "w1" };
    if (url.includes("/notifications/")) body = { notifications: [] };
    if (url.includes("/communications/?")) {
      const offset = Number(new URL(url, "http://localhost").searchParams.get("offset"));
      body = { results: Array.from({ length: offset ? 1 : 25 }, (_, index) => ({
        id: `c${offset + index + 1}`, title: `Notice ${offset + index + 1}`, status: "draft",
      })), next_offset: offset ? null : 25 };
    }
    return { status: 200, ok: true, text: async () => JSON.stringify(body) };
  });
  vi.stubGlobal("fetch", fetch);
  renderRoute(<MonitoringPage defaultTab="notifications" />, {
    path: "/ctf/admin/events/:eventId/monitoring", initialEntries: ["/ctf/admin/events/e1/monitoring"],
  });
  await screen.findByText("Notice 25 — draft");
  await userEvent.click(await screen.findByRole("button", { name: "Load more communications" }));
  const title = await screen.findByText("Notice 26 — draft");
  await userEvent.click(within(title.parentElement!).getByRole("button", { name: "Cancel unclaimed work" }));
  expect(fetch.mock.calls.some(([url, init]) => url === "/api/v1/ctf/communications/c26/cancel/" && init.method === "POST")).toBe(true);
});
