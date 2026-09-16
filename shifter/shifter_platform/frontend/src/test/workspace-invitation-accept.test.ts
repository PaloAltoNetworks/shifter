import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const invitationExchangeScript = readFileSync(
  resolve(process.cwd(), "../static/js/workspace_invitation_accept.js"),
  "utf8",
);

const FAILURE_MESSAGE =
  "This invitation could not be accepted. Ask a workspace administrator for a new invitation.";

function renderExchange(hash = "#token=invite-secret"): void {
  window.history.replaceState(null, "", `/accept${hash}`);
  document.body.innerHTML = `
    <p id="invitation-status">Preparing your invitation…</p>
    <div id="invitation-exchange" data-stage-url="/invitations/stage/"></div>
  `;
}

function executeExchangeScript(): void {
  window.eval(invitationExchangeScript);
}

describe("workspace invitation fragment exchange", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.cookie = "csrftoken=; Max-Age=0; Path=/";
    renderExchange();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("scrubs the bearer before exchanging it and follows the bounded redirect", async () => {
    document.cookie = "csrftoken=csrf%20value; Path=/";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ redirect_url: "/login/" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    let followedUrl = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      followedUrl = this.href;
    });

    executeExchangeScript();

    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("invite-secret");
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/invitations/stage/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": "csrf value" },
        body: JSON.stringify({ token: "invite-secret" }),
      });
      expect(followedUrl).toBe(new URL("/login/", window.location.href).href);
    });
  });

  it("shows a bounded failure when the exchange response is not successful", async () => {
    document.cookie = "csrftoken=csrf; Path=/";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    executeExchangeScript();

    await vi.waitFor(() => {
      expect(document.getElementById("invitation-status")).toHaveTextContent(FAILURE_MESSAGE);
    });
    expect(click).not.toHaveBeenCalled();
  });

  it("rejects a landing without a token before making a request", () => {
    renderExchange("");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    executeExchangeScript();

    expect(document.getElementById("invitation-status")).toHaveTextContent(FAILURE_MESSAGE);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a landing without a CSRF cookie before making a request", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    executeExchangeScript();

    expect(window.location.hash).toBe("");
    expect(document.getElementById("invitation-status")).toHaveTextContent(FAILURE_MESSAGE);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
