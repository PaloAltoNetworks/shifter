import { StrictMode } from "react";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const renderMock = vi.fn();
const createRootMock = vi.fn(() => ({ render: renderMock, unmount: vi.fn() }));

vi.mock("react-dom/client", () => ({ createRoot: createRootMock }));
// The entrypoint's mount behaviour is what is under test, not the route table
// (covered by router.test.tsx). Stub the router so importing main.tsx does not
// pull the entire page graph (xterm, mermaid, every feature) into this test.
const { routerStub } = vi.hoisted(() => ({ routerStub: { id: "router-stub" } }));
vi.mock("@/router", () => ({ router: routerStub }));

beforeEach(() => {
  vi.resetModules();
  renderMock.mockClear();
  createRootMock.mockClear();
  document.body.innerHTML = "";
});

describe("main entrypoint", () => {
  it("mounts the correct provider tree into the #root container", async () => {
    const root = document.createElement("div");
    root.id = "root";
    document.body.appendChild(root);

    await import("./main");

    expect(createRootMock).toHaveBeenCalledTimes(1);
    expect(createRootMock).toHaveBeenCalledWith(root);
    expect(renderMock).toHaveBeenCalledTimes(1);

    // Assert the composition, not just that render fired: StrictMode wrapping
    // QueryClientProvider (with a client) wrapping RouterProvider bound to the
    // app router. A dropped provider or wrong router must fail this test.
    const tree = renderMock.mock.calls[0][0];
    expect(tree.type).toBe(StrictMode);

    const queryProvider = tree.props.children;
    expect(queryProvider.type).toBe(QueryClientProvider);
    expect(queryProvider.props.client).toBeDefined();

    const routerProvider = queryProvider.props.children;
    expect(routerProvider.type).toBe(RouterProvider);
    expect(routerProvider.props.router).toBe(routerStub);
  });

  it("does nothing when the #root container is absent", async () => {
    await import("./main");

    expect(createRootMock).not.toHaveBeenCalled();
    expect(renderMock).not.toHaveBeenCalled();
  });
});
