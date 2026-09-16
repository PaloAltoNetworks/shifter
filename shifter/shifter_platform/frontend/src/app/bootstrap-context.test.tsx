import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/bootstrap", () => ({ useBootstrap: vi.fn() }));

import { useBootstrap } from "@/api/bootstrap";
import { ApiError } from "@/api/errors";

import { BootstrapProvider, useBootstrapContext } from "./bootstrap-context";

const mockUseBootstrap = vi.mocked(useBootstrap);

/** A child that reads the context so we can assert it was provided. */
function Child() {
  const bootstrap = useBootstrapContext();
  return <div>hello {bootstrap.principal.username}</div>;
}

type BootstrapResult = ReturnType<typeof useBootstrap>;

function state(partial: Partial<BootstrapResult>): BootstrapResult {
  return { data: undefined, isLoading: false, error: null, ...partial } as BootstrapResult;
}

beforeEach(() => {
  mockUseBootstrap.mockReset();
});

describe("BootstrapProvider", () => {
  it("shows a loading state while the session bootstrap resolves", () => {
    mockUseBootstrap.mockReturnValue(state({ isLoading: true }));

    render(
      <BootstrapProvider>
        <Child />
      </BootstrapProvider>,
    );

    expect(screen.getByLabelText("Loading workspace")).toBeInTheDocument();
  });

  it("redirects to the shared Django login on an expired (401) session", () => {
    // jsdom's location.assign is non-configurable, so stub the whole global.
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/mission-control", search: "?tab=x", assign });
    mockUseBootstrap.mockReturnValue(state({ error: new ApiError(401, { code: "unauth", message: "expired" }) }));

    const { container } = render(
      <BootstrapProvider>
        <Child />
      </BootstrapProvider>,
    );

    expect(assign).toHaveBeenCalledWith(`/login/?next=${encodeURIComponent("/mission-control?tab=x")}`);
    expect(container).toBeEmptyDOMElement();
    vi.unstubAllGlobals();
  });

  it("renders a non-leaking error state on a non-401 failure", () => {
    mockUseBootstrap.mockReturnValue(
      state({ error: new ApiError(500, { code: "err", message: "internal-secret-detail" }) }),
    );

    render(
      <BootstrapProvider>
        <Child />
      </BootstrapProvider>,
    );

    expect(screen.getByText("Unable to load the workspace")).toBeInTheDocument();
    // The raw server error message must not leak into the UI.
    expect(screen.queryByText(/internal-secret-detail/)).not.toBeInTheDocument();
  });

  it("provides the bootstrap payload to children on success", () => {
    mockUseBootstrap.mockReturnValue(state({ data: { principal: { username: "ada" } } as never }));

    render(
      <BootstrapProvider>
        <Child />
      </BootstrapProvider>,
    );

    expect(screen.getByText(/hello ada/)).toBeInTheDocument();
  });
});

describe("useBootstrapContext", () => {
  it("throws when used outside a BootstrapProvider", () => {
    // The render throws; silence the expected React error logging.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Child />)).toThrow(/useBootstrapContext must be used within a BootstrapProvider/);
    consoleError.mockRestore();
  });
});
