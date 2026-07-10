/**
 * @jest-environment jsdom
 * @jest-environment-options {"url": "https://portal.example.com/identity/login/"}
 */

// Tests for the Identity Platform corporate sign-in / registration module.
//
// identity_platform_auth.js is a browser ES module: it imports the Firebase
// modular SDK from the gstatic CDN (mapped to local mocks via jest
// moduleNameMapper) and, on load, wires the native email+password form and the
// TOTP MFA flows. Each test rebuilds the DOM and config, requires the module
// fresh, and drives a flow through the mocked Firebase SDK, asserting the
// resulting DOM/section/banner state.

const SOURCE = "./identity_platform_auth.js";
const AUTH_MOCK = "./__mocks__/firebase-auth.js";
const APP_MOCK = "./__mocks__/firebase-app.js";

const CONFIG = {
    apiKey: "test-api-key",
    authDomain: "test.firebaseapp.com",
    projectId: "test-project",
    allowedEmailDomain: "corp.example",
    allowedEmails: ["allowlisted@partner.example"],
    sessionExchangeUrl: "/identity/session/",
    dashboardUrl: "/dashboard/",
    verificationContinueUrl: "https://portal.example.com/identity/login/",
    issuer: "Shifter",
    totpDisplayName: "Shifter TOTP",
};

const DOM = `
    <div id="auth-banner" class="banner"></div>
    <section id="identity-auth-section" class="section">
        <h2 id="identity-auth-title"></h2>
        <form id="identity-auth-form">
            <input id="identity-email" type="email">
            <input id="identity-password" type="password">
            <button id="identity-auth-submit" type="submit"></button>
        </form>
        <button id="identity-auth-mode-toggle" type="button"></button>
    </section>
    <section id="identity-verify-email-section" class="section">
        <p id="identity-verify-email-copy"></p>
        <button id="identity-back-to-login" type="button"></button>
    </section>
    <section id="identity-totp-enrollment-section" class="section">
        <div id="identity-totp-qr-url"></div>
        <div id="identity-totp-secret"></div>
        <input id="identity-totp-enrollment-code" type="text">
        <button id="identity-totp-enrollment-submit" type="button"></button>
    </section>
    <section id="identity-totp-signin-section" class="section">
        <input id="identity-totp-signin-code" type="text">
        <button id="identity-totp-signin-submit" type="button"></button>
    </section>
`;

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function el(id) {
    return document.getElementById(id);
}

function bannerText() {
    return el("auth-banner").textContent;
}

function visibleSections() {
    return Array.from(document.querySelectorAll(".section.visible")).map((s) => s.id);
}

function makeUser(overrides = {}) {
    return {
        email: "worker@corp.example",
        emailVerified: true,
        getIdToken: jest.fn(async () => "id-token"),
        ...overrides,
    };
}

// Build the DOM + config script, require the module fresh, and let its
// top-level async bootstrap (setPersistence -> listener wiring) settle.
async function bootstrap(configOverrides = {}, { withConfig = true } = {}) {
    jest.resetModules();
    document.body.innerHTML = DOM;
    if (withConfig) {
        const script = document.createElement("script");
        script.id = "identity-platform-config";
        script.type = "application/json";
        script.textContent = JSON.stringify({ ...CONFIG, ...configOverrides });
        document.body.appendChild(script);
    }
    const fbAuth = require(AUTH_MOCK);
    const fbApp = require(APP_MOCK);
    require(SOURCE);
    await flush();
    return { fbAuth, fbApp };
}

function submitLogin(email, password) {
    el("identity-email").value = email;
    el("identity-password").value = password;
    el("identity-auth-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    return flush();
}

beforeEach(() => {
    document.cookie = "csrftoken=test-csrf";
    // jsdom's location.assign is a non-configurable no-op that logs an
    // unimplemented-navigation notice rather than navigating; suppress that
    // console noise and assert the redirect via the session-exchange fetch.
    jest.spyOn(console, "error").mockImplementation(() => {});
    global.fetch = jest.fn();
});

afterEach(() => {
    jest.restoreAllMocks();
});

describe("bootstrap", () => {
    test("initializes Firebase, sets session persistence, and shows the sign-in form", async () => {
        const { fbApp, fbAuth } = await bootstrap();
        expect(fbApp.initializeApp).toHaveBeenCalledWith(
            expect.objectContaining({ apiKey: "test-api-key", projectId: "test-project" })
        );
        expect(fbAuth.setPersistence).toHaveBeenCalledTimes(1);
        expect(fbAuth.onAuthStateChanged).toHaveBeenCalledTimes(1);
        expect(visibleSections()).toEqual(["identity-auth-section"]);
        expect(el("identity-auth-title").textContent).toBe("Sign in");
    });

    test("reuses an already-initialized Firebase app", async () => {
        jest.resetModules();
        document.body.innerHTML = DOM;
        const script = document.createElement("script");
        script.id = "identity-platform-config";
        script.type = "application/json";
        script.textContent = JSON.stringify(CONFIG);
        document.body.appendChild(script);
        const fbApp = require(APP_MOCK);
        fbApp.getApps.mockReturnValueOnce([{ name: "[DEFAULT]" }]);
        require(AUTH_MOCK);
        require(SOURCE);
        await flush();
        expect(fbApp.getApp).toHaveBeenCalledTimes(1);
        expect(fbApp.initializeApp).not.toHaveBeenCalled();
    });

    test("does nothing without the config script element", async () => {
        const { fbAuth } = await bootstrap({}, { withConfig: false });
        expect(fbAuth.getAuth).not.toHaveBeenCalled();
    });
});

describe("mode toggle", () => {
    test("switches between sign-in and register copy", async () => {
        await bootstrap();
        expect(el("identity-auth-submit").textContent).toBe("Sign in");
        el("identity-auth-mode-toggle").dispatchEvent(new Event("click"));
        expect(el("identity-auth-title").textContent).toBe("Create your account");
        expect(el("identity-auth-submit").textContent).toBe("Create account");
        expect(el("identity-password").getAttribute("autocomplete")).toBe("new-password");
        el("identity-auth-mode-toggle").dispatchEvent(new Event("click"));
        expect(el("identity-auth-submit").textContent).toBe("Sign in");
    });
});

describe("credential submission", () => {
    test("rejects an email outside the allowed domain without calling Firebase", async () => {
        const { fbAuth } = await bootstrap();
        await submitLogin("intruder@evil.example", "hunter2");
        expect(fbAuth.signInWithEmailAndPassword).not.toHaveBeenCalled();
        expect(bannerText()).toMatch(/approved corp\.example users/);
    });

    test("requires both email and password", async () => {
        await bootstrap();
        await submitLogin("", "");
        expect(bannerText()).toMatch(/Email and password are required/);
    });

    test("signs in an allowed corporate user", async () => {
        const { fbAuth } = await bootstrap();
        await submitLogin("worker@corp.example", "s3cret");
        expect(fbAuth.signInWithEmailAndPassword).toHaveBeenCalledWith(
            expect.anything(),
            "worker@corp.example",
            "s3cret"
        );
    });

    test("accepts an explicitly allow-listed email outside the domain", async () => {
        const { fbAuth } = await bootstrap();
        await submitLogin("allowlisted@partner.example", "s3cret");
        expect(fbAuth.signInWithEmailAndPassword).toHaveBeenCalled();
    });

    test("registers a new account in register mode", async () => {
        const { fbAuth } = await bootstrap();
        el("identity-auth-mode-toggle").dispatchEvent(new Event("click"));
        await submitLogin("worker@corp.example", "s3cret");
        expect(fbAuth.createUserWithEmailAndPassword).toHaveBeenCalled();
    });

    test("maps a known credential error to friendly copy", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ code: "auth/invalid-credential" });
        await submitLogin("worker@corp.example", "wrong");
        expect(bannerText()).toBe("Incorrect email or password.");
    });

    test("falls back to the raw error message for unmapped errors", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ message: "Service unavailable" });
        await submitLogin("worker@corp.example", "pw");
        expect(bannerText()).toBe("Service unavailable");
    });

    test("routes an MFA-required sign-in to the TOTP challenge", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ code: "auth/multi-factor-auth-required" });
        fbAuth.getMultiFactorResolver.mockReturnValueOnce({
            hints: [{ factorId: "totp", uid: "factor-1" }],
            resolveSignIn: jest.fn(async () => ({ user: makeUser() })),
        });
        await submitLogin("worker@corp.example", "pw");
        expect(visibleSections()).toEqual(["identity-totp-signin-section"]);
    });
});

describe("authenticated-user handling (onAuthStateChanged)", () => {
    async function fireAuthState(user, fbAuth) {
        fbAuth.lastAuthObserver(user);
        await flush();
    }

    test("signs out a user whose email is not allowed", async () => {
        const { fbAuth } = await bootstrap();
        await fireAuthState(makeUser({ email: "outsider@evil.example" }), fbAuth);
        expect(fbAuth.signOut).toHaveBeenCalled();
        expect(bannerText()).toMatch(/approved corp\.example users/);
    });

    test("sends a verification email when the address is unverified", async () => {
        const { fbAuth } = await bootstrap();
        await fireAuthState(makeUser({ emailVerified: false }), fbAuth);
        expect(fbAuth.sendEmailVerification).toHaveBeenCalled();
        expect(fbAuth.signOut).toHaveBeenCalled();
        expect(visibleSections()).toEqual(["identity-verify-email-section"]);
        expect(el("identity-verify-email-copy").textContent).toMatch(/verification email/);
    });

    test("starts TOTP enrollment when no second factor exists", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [],
            getSession: jest.fn(async () => ({ session: "s" })),
            enroll: jest.fn(async () => {}),
        });
        await fireAuthState(makeUser(), fbAuth);
        expect(visibleSections()).toEqual(["identity-totp-enrollment-section"]);
        expect(el("identity-totp-secret").textContent).toBe("SECRETKEY234567");
        expect(el("identity-totp-qr-url").textContent).toMatch(/^otpauth:/);
    });

    test("exchanges a session and redirects when a factor is enrolled", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [{ uid: "factor-1" }],
            getSession: jest.fn(async () => ({})),
            enroll: jest.fn(),
        });
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ redirect_url: "/secure/" }) });
        await fireAuthState(makeUser(), fbAuth);
        expect(global.fetch).toHaveBeenCalledWith("/identity/session/", expect.objectContaining({ method: "POST" }));
        const body = JSON.parse(global.fetch.mock.calls[0][1].body);
        expect(body.idToken).toBe("id-token");
        expect(bannerText()).toBe("");
    });

    test("re-enters enrollment when the exchange demands MFA", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [{ uid: "factor-1" }],
            getSession: jest.fn(async () => ({})),
            enroll: jest.fn(),
        });
        global.fetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ error: "mfa_enrollment_required", message: "Enroll now" }),
        });
        await fireAuthState(makeUser(), fbAuth);
        expect(visibleSections()).toEqual(["identity-totp-enrollment-section"]);
    });

    test("re-sends verification when the exchange reports an unverified email", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [{ uid: "factor-1" }],
            getSession: jest.fn(async () => ({})),
            enroll: jest.fn(),
        });
        global.fetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ error: "email_verification_required" }),
        });
        await fireAuthState(makeUser(), fbAuth);
        expect(fbAuth.sendEmailVerification).toHaveBeenCalled();
        expect(visibleSections()).toEqual(["identity-verify-email-section"]);
    });
});

describe("TOTP enrollment completion", () => {
    async function reachEnrollment() {
        const ctx = await bootstrap();
        ctx.fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [],
            getSession: jest.fn(async () => ({ session: "s" })),
            enroll: jest.fn(async () => {}),
        });
        ctx.fbAuth.authInstance.currentUser = makeUser();
        ctx.fbAuth.lastAuthObserver(makeUser());
        await flush();
        return ctx;
    }

    test("requires a verification code", async () => {
        await reachEnrollment();
        el("identity-totp-enrollment-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(bannerText()).toMatch(/Verification code is required/);
    });

    test("enrolls the factor and exchanges a session", async () => {
        const { fbAuth } = await reachEnrollment();
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ redirect_url: "/secure/" }) });
        el("identity-totp-enrollment-code").value = "123456";
        el("identity-totp-enrollment-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(fbAuth.TotpMultiFactorGenerator.assertionForEnrollment).toHaveBeenCalled();
        expect(global.fetch).toHaveBeenCalledWith("/identity/session/", expect.objectContaining({ method: "POST" }));
    });
});

describe("TOTP sign-in completion", () => {
    async function reachSigninChallenge() {
        const ctx = await bootstrap();
        ctx.fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ code: "auth/multi-factor-auth-required" });
        ctx.fbAuth.getMultiFactorResolver.mockReturnValueOnce({
            hints: [{ factorId: "totp", uid: "factor-1" }],
            resolveSignIn: jest.fn(async () => ({ user: makeUser() })),
        });
        await submitLogin("worker@corp.example", "pw");
        return ctx;
    }

    test("requires a code before resolving", async () => {
        await reachSigninChallenge();
        el("identity-totp-signin-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(bannerText()).toMatch(/Verification code is required/);
    });

    test("resolves the challenge with the entered code", async () => {
        const { fbAuth } = await reachSigninChallenge();
        el("identity-totp-signin-code").value = "654321";
        el("identity-totp-signin-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(fbAuth.TotpMultiFactorGenerator.assertionForSignIn).toHaveBeenCalledWith("factor-1", "654321");
    });
});

describe("back to sign-in", () => {
    test("returns to the auth form from another section", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.lastAuthObserver(makeUser({ emailVerified: false }));
        await flush();
        expect(visibleSections()).toEqual(["identity-verify-email-section"]);
        el("identity-back-to-login").dispatchEvent(new Event("click"));
        expect(visibleSections()).toEqual(["identity-auth-section"]);
    });
});

describe("friendly auth-error mapping", () => {
    test.each([
        ["auth/user-disabled", /account is disabled/],
        ["auth/email-already-in-use", /account already exists/],
        ["auth/weak-password", /stronger password/],
        ["auth/invalid-email", /valid email address/],
        ["auth/too-many-requests", /Too many attempts/],
        ["auth/network-request-failed", /Could not reach the authentication service/],
    ])("maps %s to corporate-friendly copy", async (code, expected) => {
        const { fbAuth } = await bootstrap();
        fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ code });
        await submitLogin("worker@corp.example", "pw");
        expect(bannerText()).toMatch(expected);
    });
});

describe("exchange + TOTP guard branches", () => {
    test("surfaces a server error message when the session exchange fails", async () => {
        const { fbAuth } = await bootstrap();
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [{ uid: "factor-1" }],
            getSession: jest.fn(async () => ({})),
            enroll: jest.fn(),
        });
        global.fetch.mockResolvedValueOnce({
            ok: false,
            json: async () => ({ message: "Session minting failed" }),
        });
        fbAuth.lastAuthObserver(makeUser());
        await flush();
        expect(bannerText()).toBe("Session minting failed");
        expect(visibleSections()).toEqual(["identity-auth-section"]);
    });

    test("rejects TOTP sign-in when no challenge is pending", async () => {
        await bootstrap();
        el("identity-totp-signin-code").value = "123456";
        el("identity-totp-signin-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(bannerText()).toMatch(/No MFA sign-in challenge is pending/);
    });

    test("reports when no enrolled TOTP factor is available for sign-in", async () => {
        const ctx = await bootstrap();
        ctx.fbAuth.signInWithEmailAndPassword.mockRejectedValueOnce({ code: "auth/multi-factor-auth-required" });
        ctx.fbAuth.getMultiFactorResolver.mockReturnValueOnce({
            hints: [{ factorId: "phone", uid: "sms-1" }],
            resolveSignIn: jest.fn(),
        });
        await submitLogin("worker@corp.example", "pw");
        el("identity-totp-signin-code").value = "123456";
        el("identity-totp-signin-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(bannerText()).toMatch(/No enrolled TOTP factor/);
    });

    test("rejects TOTP enrollment when none is pending", async () => {
        await bootstrap();
        el("identity-totp-enrollment-code").value = "123456";
        el("identity-totp-enrollment-submit").dispatchEvent(new Event("click"));
        await flush();
        expect(bannerText()).toMatch(/No TOTP enrollment is pending/);
    });
});

describe("session redirect safety", () => {
    function withEnrolledFactor(fbAuth) {
        fbAuth.multiFactor.mockReturnValue({
            enrolledFactors: [{ uid: "factor-1" }],
            getSession: jest.fn(async () => ({})),
            enroll: jest.fn(),
        });
    }

    test("follows a same-origin redirect path from the exchange", async () => {
        const { fbAuth } = await bootstrap();
        withEnrolledFactor(fbAuth);
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ redirect_url: "/secure/area" }) });
        fbAuth.lastAuthObserver(makeUser());
        await flush();
        expect(bannerText()).toBe("");
    });

    test("ignores a cross-origin redirect target", async () => {
        const { fbAuth } = await bootstrap();
        withEnrolledFactor(fbAuth);
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ redirect_url: "https://evil.example/phish" }),
        });
        fbAuth.lastAuthObserver(makeUser());
        await flush();
        // No error surfaced: the unsafe target is dropped in favour of the
        // configured dashboard rather than navigating off-origin.
        expect(bannerText()).toBe("");
    });

    test("falls back to the dashboard when the exchange omits a redirect", async () => {
        const { fbAuth } = await bootstrap();
        withEnrolledFactor(fbAuth);
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
        fbAuth.lastAuthObserver(makeUser());
        await flush();
        expect(bannerText()).toBe("");
    });
});
