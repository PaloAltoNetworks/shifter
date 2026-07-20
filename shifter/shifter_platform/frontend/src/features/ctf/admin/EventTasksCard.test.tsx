import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { EventTasksCard } from "./EventTasksCard";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => mockApi.mockReset());

const TASKS = {
  tasks: [
    {
      id: "t1",
      task_type: "event_start",
      status: "pending",
      scheduled_for: "2026-08-01T10:00:00Z",
      executed_at: null,
      error_message: "",
      retry_count: 0,
    },
    {
      id: "t2",
      task_type: "cleanup_ranges",
      status: "pending",
      scheduled_for: "2026-08-02T10:00:00Z",
      executed_at: null,
      error_message: "",
      retry_count: 0,
    },
    {
      id: "t3",
      task_type: "send_reminder",
      status: "failed",
      scheduled_for: "2026-07-30T10:00:00Z",
      executed_at: "2026-07-30T10:00:05Z",
      error_message: "smtp down",
      retry_count: 3,
    },
  ],
};

describe("EventTasksCard", () => {
  it("lists tasks with status, retries, and errors", async () => {
    mockApi.mockResolvedValue(TASKS);
    renderRoute(<EventTasksCard eventId="e1" />);
    expect(await screen.findByText("Event start")).toBeInTheDocument();
    expect(screen.getByText("smtp down")).toBeInTheDocument();
    expect(screen.getByText("retry 3")).toBeInTheDocument();
    // Only pending tasks offer run-now.
    expect(screen.getAllByRole("button", { name: "Run now" })).toHaveLength(2);
  });

  it("runs a pending task now", async () => {
    mockApi.mockResolvedValue(TASKS);
    renderRoute(<EventTasksCard eventId="e1" />);
    await userEvent.click((await screen.findAllByRole("button", { name: "Run now" }))[0]);
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/tasks/t1/run/",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("defers and cancels pending cleanup", async () => {
    mockApi.mockResolvedValue(TASKS);
    renderRoute(<EventTasksCard eventId="e1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Defer cleanup" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/cleanup/",
      expect.objectContaining({ method: "POST", body: { action: "defer", hours: 2 } }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel automated cleanup" }));
    expect(mockApi).toHaveBeenCalledWith(
      "/ctf/events/e1/cleanup/",
      expect.objectContaining({ method: "POST", body: { action: "cancel" } }),
    );
  });

  it("hides cleanup controls without a pending cleanup", async () => {
    mockApi.mockResolvedValue({ tasks: [TASKS.tasks[0]] });
    renderRoute(<EventTasksCard eventId="e1" />);
    await screen.findByText("Event start");
    expect(screen.queryByRole("button", { name: "Defer cleanup" })).not.toBeInTheDocument();
  });
});
