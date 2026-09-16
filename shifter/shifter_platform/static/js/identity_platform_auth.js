// Identity Platform corporate sign-in / registration.
//
// Uses the Firebase modular Web SDK (loaded from the version-pinned gstatic CDN)
// rather than the compat build: the compat namespace ships PhoneMultiFactorGenerator
// but not TotpMultiFactorGenerator, so TOTP MFA enrollment is only available
// through the modular API. A native email + password form replaces FirebaseUI,
// whose email-first flow depends on fetchSignInMethodsForEmail and therefore
// breaks once Identity Platform email enumeration protection is enabled.
import { initializeApp, getApps, getApp } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js";
import {
    getAuth,
    setPersistence,
    browserSessionPersistence,
    onAuthStateChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signOut,
    reload,
    sendEmailVerification,
    multiFactor,
    getMultiFactorResolver,
    TotpMultiFactorGenerator,
} from "https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js";

// Resolve a redirect target to a safe, same-origin path, or null otherwise.
// Only a root-relative path ("/path") that is NOT protocol-relative ("//host")
// is allowed: this rejects absolute URLs, "javascript:" targets, and any
// off-origin destination, so the value handed to location.assign can never
// navigate (or script) off this origin. The session-exchange response and
// injected config are trusted; this keeps an open redirect / DOM-XSS impossible
// even if either is tampered with (CodeQL js/xss-through-dom). Hoisted to module
// scope and exported so it can be unit-tested directly, mirroring
// identity_platform_logout.js.
const SAFE_REDIRECT_PATH = /^\/(?!\/)[\w\-./~!$&'()*+,;=:@%?#[\]]*$/;
function sameOriginPath(candidate) {
    if (typeof candidate === "string" && SAFE_REDIRECT_PATH.test(candidate)) {
        return candidate;
    }
    return null;
}

// Resolve the post-exchange navigation target by running BOTH the server-supplied
// redirect and the configured dashboard through the same-origin guard, falling
// back to the site root. Extracted and exported so a unit test asserts the guard
// is actually applied to each candidate (jsdom's location.assign is an
// unspyable no-op, so the sink itself cannot be observed) — this fails if the
// guard is dropped from the resolution, which banner-text assertions cannot
// detect (issue #1920).
function resolveRedirectDestination(redirectUrl, dashboardUrl) {
    return sameOriginPath(redirectUrl) || sameOriginPath(dashboardUrl) || "/";
}

export { sameOriginPath, resolveRedirectDestination };

const configScript = document.getElementById("identity-platform-config");
if (configScript) {
    const config = JSON.parse(configScript.textContent);
    const app = getApps().length
        ? getApp()
        : initializeApp({
              apiKey: config.apiKey,
              authDomain: config.authDomain,
              projectId: config.projectId,
          });
    const auth = getAuth(app);

    let handlingAuthState = false;
    let pendingTotpSecret = null;
    let pendingResolver = null;
    let pendingVerificationEmail = "";
    // "signin" collects existing credentials; "register" provisions a new
    // corporate account via createUserWithEmailAndPassword.
    let authMode = "signin";

    const sections = {
        auth: document.getElementById("identity-auth-section"),
        verifyEmail: document.getElementById("identity-verify-email-section"),
        enrollTotp: document.getElementById("identity-totp-enrollment-section"),
        signinTotp: document.getElementById("identity-totp-signin-section"),
    };
    const banner = document.getElementById("auth-banner");

    const authForm = document.getElementById("identity-auth-form");
    const emailInput = document.getElementById("identity-email");
    const passwordInput = document.getElementById("identity-password");
    const submitButton = document.getElementById("identity-auth-submit");
    const modeToggle = document.getElementById("identity-auth-mode-toggle");
    const formTitle = document.getElementById("identity-auth-title");

    function setVisibleSection(key) {
        Object.values(sections).forEach((section) => section.classList.remove("visible"));
        const targetSection = sections[key];
        if (!targetSection) {
            throw new Error(`Unknown auth section: ${key}`);
        }
        targetSection.classList.add("visible");
    }

    function showBanner(kind, message) {
        banner.textContent = message;
        banner.className = `banner visible ${kind}`;
    }

    function clearBanner() {
        banner.textContent = "";
        banner.className = "banner";
    }

    function csrfToken() {
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith("csrftoken="))
            ?.split("=")[1];
    }

    // Provider errors are mapped to fixed, authored copy selected only by the
    // stable error code. The default never echoes error.message or any raw
    // provider/exception text to the anonymous page (issue #1920), and the
    // credential cases stay deliberately generic to preserve email-enumeration
    // protection (they never reveal whether an account exists).
    function friendlyAuthError(error) {
        switch (error?.code) {
            case "auth/invalid-credential":
            case "auth/invalid-login-credentials":
            case "auth/wrong-password":
            case "auth/user-not-found":
                return "Incorrect email or password.";
            case "auth/user-disabled":
                return "This account is disabled. Contact an administrator.";
            case "auth/email-already-in-use":
                return "An account already exists for this email. Switch to sign in.";
            case "auth/weak-password":
                return "Choose a stronger password (at least six characters).";
            case "auth/invalid-email":
                return "Enter a valid email address.";
            case "auth/too-many-requests":
                return "Too many attempts. Wait a moment and try again.";
            case "auth/network-request-failed":
                return "Could not reach the authentication service. Check your network and try again.";
            default:
                return "Unable to complete sign-in. Please try again.";
        }
    }

    async function exchangeSession(user) {
        const idToken = await user.getIdToken(true);
        const response = await fetch(config.sessionExchangeUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken() || "",
            },
            body: JSON.stringify({ idToken }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            // Branch only on the fixed server error code; never display the
            // server-provided message on the anonymous page (issue #1920).
            if (body.error === "email_verification_required") {
                await sendVerification(user);
                return;
            }
            if (body.error === "mfa_enrollment_required") {
                await startTotpEnrollment(user, "");
                return;
            }
            throw new Error("session_exchange_failed");
        }
        globalThis.location.assign(resolveRedirectDestination(body.redirect_url, config.dashboardUrl));
    }

    async function sendVerification(user) {
        await sendEmailVerification(user, {
            url: config.verificationContinueUrl,
            handleCodeInApp: false,
        });
        pendingVerificationEmail = user.email || "";
        await signOut(auth);
        document.getElementById("identity-verify-email-copy").textContent =
            `A verification email has been sent to ${pendingVerificationEmail}. Open the link in that email, then return here to sign in again.`;
        clearBanner();
        setVisibleSection("verifyEmail");
    }

    async function handleAuthenticatedUser(user, isNewUser) {
        if (!user || handlingAuthState) {
            return;
        }

        handlingAuthState = true;
        clearBanner();

        try {
            await reload(user);

            // Email admission is enforced authoritatively at the server session
            // exchange (IdentityPlatformBackend) and at registration by the
            // provider beforeCreate hook; the browser deliberately carries no
            // allowlist policy to disclose (issue #1920).
            if (!user.emailVerified) {
                await sendVerification(user);
                if (isNewUser) {
                    showBanner("success", "Verify your email to finish activating your account.");
                }
                return;
            }

            const factors = multiFactor(user).enrolledFactors;
            if (!factors.length) {
                await startTotpEnrollment(user, "");
                return;
            }

            await exchangeSession(user);
        } catch (error) {
            showBanner("error", friendlyAuthError(error));
            showAuthForm();
        } finally {
            handlingAuthState = false;
        }
    }

    async function startTotpEnrollment(user, message) {
        const multiFactorSession = await multiFactor(user).getSession();
        pendingTotpSecret = await TotpMultiFactorGenerator.generateSecret(multiFactorSession);

        const otpauthUrl = pendingTotpSecret.generateQrCodeUrl(user.email, config.issuer);
        const qrEl = document.getElementById("identity-totp-qr-url");
        qrEl.textContent = "";
        // Render the otpauth URL as a scannable QR image (client-side; the TOTP
        // secret never leaves the browser). Falls back to the raw URL if the
        // vendored QR library failed to load.
        try {
            const qr = globalThis.qrcode(0, "M");
            qr.addData(otpauthUrl);
            qr.make();
            const img = document.createElement("img");
            img.src = qr.createDataURL(5, 8);
            img.alt = "Authenticator setup QR code";
            qrEl.appendChild(img);
        } catch (err) {
            console.warn("TOTP QR render failed; showing the otpauth URL instead", err);
            qrEl.textContent = otpauthUrl;
        }
        document.getElementById("identity-totp-secret").textContent = pendingTotpSecret.secretKey;
        document.getElementById("identity-totp-enrollment-code").value = "";
        if (message) {
            showBanner("success", message);
        } else {
            clearBanner();
        }
        setVisibleSection("enrollTotp");
    }

    async function completeTotpEnrollment() {
        const code = document.getElementById("identity-totp-enrollment-code").value.trim();
        if (!code) {
            showBanner("error", "Verification code is required.");
            return;
        }
        if (!pendingTotpSecret || !auth.currentUser) {
            showBanner("error", "No TOTP enrollment is pending.");
            return;
        }

        try {
            const assertion = TotpMultiFactorGenerator.assertionForEnrollment(pendingTotpSecret, code);
            await multiFactor(auth.currentUser).enroll(assertion, config.totpDisplayName);
            pendingTotpSecret = null;
            await exchangeSession(auth.currentUser);
        } catch (error) {
            showBanner("error", friendlyAuthError(error));
        }
    }

    async function completeTotpSignIn() {
        const code = document.getElementById("identity-totp-signin-code").value.trim();
        if (!code) {
            showBanner("error", "Verification code is required.");
            return;
        }
        if (!pendingResolver) {
            showBanner("error", "No MFA sign-in challenge is pending.");
            return;
        }

        const hint = pendingResolver.hints.find(
            (candidate) => candidate.factorId === TotpMultiFactorGenerator.FACTOR_ID
        );
        if (!hint) {
            showBanner("error", "No authenticator app is set up for this account.");
            return;
        }

        try {
            const assertion = TotpMultiFactorGenerator.assertionForSignIn(hint.uid, code);
            const userCredential = await pendingResolver.resolveSignIn(assertion);
            pendingResolver = null;
            await handleAuthenticatedUser(userCredential.user, false);
        } catch (error) {
            showBanner("error", friendlyAuthError(error));
        }
    }

    function renderAuthMode() {
        if (authMode === "register") {
            formTitle.textContent = "Create your account";
            submitButton.textContent = "Create account";
            modeToggle.textContent = "Already have an account? Sign in";
            passwordInput.setAttribute("autocomplete", "new-password");
        } else {
            formTitle.textContent = "Sign in";
            submitButton.textContent = "Sign in";
            modeToggle.textContent = "Need an account? Create one";
            passwordInput.setAttribute("autocomplete", "current-password");
        }
    }

    function showAuthForm() {
        setVisibleSection("auth");
        renderAuthMode();
    }

    async function submitCredentials() {
        const email = String(emailInput.value || "").trim();
        const password = passwordInput.value || "";
        if (!email || !password) {
            showBanner("error", "Email and password are required.");
            return;
        }

        submitButton.disabled = true;
        try {
            if (authMode === "register") {
                await createUserWithEmailAndPassword(auth, email, password);
            } else {
                await signInWithEmailAndPassword(auth, email, password);
            }
            // Success drives onAuthStateChanged -> handleAuthenticatedUser, which
            // owns email-verification and MFA enrollment. A sign-in for an account
            // that already has a second factor rejects here with the resolver.
        } catch (error) {
            if (error?.code === "auth/multi-factor-auth-required") {
                pendingResolver = getMultiFactorResolver(auth, error);
                document.getElementById("identity-totp-signin-code").value = "";
                clearBanner();
                setVisibleSection("signinTotp");
                return;
            }
            showBanner("error", friendlyAuthError(error));
        } finally {
            submitButton.disabled = false;
        }
    }

    // Set session persistence BEFORE registering the auth-state observer so the
    // first auth-state event already uses SESSION (not the default LOCAL)
    // persistence -- a deliberate security choice. A named async setup function
    // preserves that ordering without a module-level `await`: this
    // `<script type="module">` entry point is transpiled to CommonJS by the
    // jsdom test harness, which cannot represent top-level await, so S7785
    // (prefer top-level await) is unsatisfiable here without breaking the suite.
    async function initSessionPersistenceAndObserver() {
        await setPersistence(auth, browserSessionPersistence);
        onAuthStateChanged(auth, (user) => {
            if (user) {
                void handleAuthenticatedUser(user, false);
            }
        });
    }
    initSessionPersistenceAndObserver(); // NOSONAR

    authForm.addEventListener("submit", (event) => {
        event.preventDefault();
        void submitCredentials();
    });
    modeToggle.addEventListener("click", () => {
        authMode = authMode === "register" ? "signin" : "register";
        clearBanner();
        renderAuthMode();
        emailInput.focus();
    });
    document.getElementById("identity-totp-enrollment-submit").addEventListener("click", () => {
        void completeTotpEnrollment();
    });
    document.getElementById("identity-totp-signin-submit").addEventListener("click", () => {
        void completeTotpSignIn();
    });
    document.getElementById("identity-back-to-login").addEventListener("click", () => {
        clearBanner();
        showAuthForm();
    });

    showAuthForm();
}
