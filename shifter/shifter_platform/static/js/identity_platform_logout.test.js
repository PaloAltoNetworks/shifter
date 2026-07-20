/**
 * @jest-environment jsdom
 * @jest-environment-options {"url": "https://portal.example.com/identity/logout/"}
 */

// Tests for the Identity Platform logout module.
//
// identity_platform_logout.js is a browser ES module: it imports the Firebase
// modular SDK from the gstatic CDN (mapped to local mocks via jest
// moduleNameMapper) and, on load, signs the user out and navigates to a
// validated same-origin path. jsdom's location.assign is a non-configurable
// no-op that logs an unimplemented-navigation notice, so the redirect target is
// asserted through the exported sameOriginPath guard rather than the sink.

const SOURCE = "./identity_platform_logout.js";
const AUTH_MOCK = "./__mocks__/firebase-auth.js";
const APP_MOCK = "./__mocks__/firebase-app.js";

const CONFIG = {
    apiKey: "test-api-key",
    authDomain: "test.firebaseapp.com",
    projectId: "test-project",
    redirectUrl: "/dashboard/",
};

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function loadModule({ withConfig = true, config = CONFIG } = {}) {
    jest.resetModules();
    document.body.innerHTML = "";
    if (withConfig) {
        const script = document.createElement("script");
        script.id = "identity-platform-logout-config";
        script.type = "application/json";
        script.textContent = JSON.stringify(config);
        document.body.appendChild(script);
    }
    const fbAuth = require(AUTH_MOCK);
    const fbApp = require(APP_MOCK);
    const mod = require(SOURCE);
    return { fbAuth, fbApp, mod };
}

beforeEach(() => {
    // Suppress jsdom's unimplemented-navigation notice from location.assign.
    jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
    jest.restoreAllMocks();
});

describe("sameOriginPath", () => {
    let sameOriginPath;
    beforeEach(() => {
        ({
            mod: { sameOriginPath },
        } = loadModule({ withConfig: false }));
    });

    test.each([
        ["/dashboard/"],
        ["/ctf/events/42?tab=scores#top"],
        ["/"],
    ])("accepts same-origin path %s", (input) => {
        expect(sameOriginPath(input)).toBe(input);
    });

    test.each([
        ["//evil.example/path"], // protocol-relative
        ["https://evil.example/"], // absolute URL
        ["javascript:alert(1)"], // script scheme
        ["/\\evil.example"], // backslash escape
        ["dashboard"], // missing leading slash
        [""], // empty
        [null],
        [undefined],
        [42],
    ])("rejects unsafe redirect %p", (input) => {
        expect(sameOriginPath(input)).toBeNull();
    });
});

describe("module bootstrap", () => {
    test("signs the user out when config is present", async () => {
        const { fbAuth, fbApp } = loadModule({ withConfig: true });
        await flush();
        expect(fbApp.initializeApp).toHaveBeenCalledWith(
            expect.objectContaining({ apiKey: "test-api-key", projectId: "test-project" })
        );
        expect(fbAuth.signOut).toHaveBeenCalledTimes(1);
    });

    test("does not sign out when the config element is absent", () => {
        const { fbAuth } = loadModule({ withConfig: false });
        expect(fbAuth.signOut).not.toHaveBeenCalled();
    });
});

describe("runLogout", () => {
    test("logs and continues when sign-out fails", async () => {
        const { fbAuth, mod } = loadModule({ withConfig: false });
        fbAuth.signOut.mockRejectedValueOnce(new Error("network down"));
        await mod.runLogout({ apiKey: "k", redirectUrl: "/x/" });
        expect(console.error).toHaveBeenCalledWith(
            "Identity Platform logout failed",
            expect.any(Error)
        );
    });
});
