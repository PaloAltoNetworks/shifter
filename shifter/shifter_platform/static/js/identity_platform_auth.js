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

    function isAllowedEmail(email) {
        const normalized = String(email || "").trim().toLowerCase();
        if (!normalized) {
            return false;
        }
        if (Array.isArray(config.allowedEmails) && config.allowedEmails.includes(normalized)) {
            return true;
        }
        return normalized.endsWith(`@${config.allowedEmailDomain}`);
    }

    // Identity Platform returns deliberately generic credential errors when email
    // enumeration protection is on, so map the codes to corporate-friendly copy
    // without leaking whether an account exists.
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
                return error?.message || "Unable to authenticate.";
        }
    }

    // Resolve a redirect target to a safe, same-origin path, or null otherwise.
    // Only a root-relative path ("/path") that is NOT protocol-relative
    // ("//host") is allowed: this rejects absolute URLs, "javascript:" targets,
    // and any off-origin destination, so the value handed to location.assign can
    // never navigate (or script) off this origin. The session-exchange response
    // and injected config are trusted; this keeps an open redirect / DOM-XSS
    // impossible even if either is tampered with.
    const SAFE_REDIRECT_PATH = /^\/(?!\/)[\w\-./~!$&'()*+,;=:@%?#[\]]*$/;
    function sameOriginPath(candidate) {
        if (typeof candidate === "string" && SAFE_REDIRECT_PATH.test(candidate)) {
            return candidate;
        }
        return null;
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
            if (body.error === "email_verification_required") {
                await sendVerification(user);
                return;
            }
            if (body.error === "mfa_enrollment_required") {
                await startTotpEnrollment(user, body.message);
                return;
            }
            throw new Error(body.message || "Authentication failed.");
        }
        const destination = sameOriginPath(body.redirect_url) || sameOriginPath(config.dashboardUrl) || "/";
        globalThis.location.assign(destination);
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

            if (!isAllowedEmail(user.email || "")) {
                await signOut(auth);
                throw new Error(`Only approved ${config.allowedEmailDomain} users may access the corporate portal.`);
            }

            if (!user.emailVerified) {
                await sendVerification(user);
                if (isNewUser) {
                    showBanner("success", "Verify your corporate email to finish activating your account.");
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
            console.error(error);
            showBanner("error", error.message || "Unable to complete sign-in.");
            showAuthForm();
        } finally {
            handlingAuthState = false;
        }
    }

    async function startTotpEnrollment(user, message) {
        const multiFactorSession = await multiFactor(user).getSession();
        pendingTotpSecret = await TotpMultiFactorGenerator.generateSecret(multiFactorSession);

        document.getElementById("identity-totp-qr-url").textContent = pendingTotpSecret.generateQrCodeUrl(
            user.email,
            config.issuer
        );
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
            console.error(error);
            showBanner("error", error.message || "Unable to finish TOTP enrollment.");
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

        try {
            const hint = pendingResolver.hints.find(
                (candidate) => candidate.factorId === TotpMultiFactorGenerator.FACTOR_ID
            );
            if (!hint) {
                throw new Error("No enrolled TOTP factor is available for sign-in.");
            }

            const assertion = TotpMultiFactorGenerator.assertionForSignIn(hint.uid, code);
            const userCredential = await pendingResolver.resolveSignIn(assertion);
            pendingResolver = null;
            await handleAuthenticatedUser(userCredential.user, false);
        } catch (error) {
            console.error(error);
            showBanner("error", error.message || "Unable to complete MFA sign-in.");
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
        if (!isAllowedEmail(email)) {
            showBanner("error", `Only approved ${config.allowedEmailDomain} users may access the corporate portal.`);
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
            console.error(error);
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
