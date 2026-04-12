/* global firebase, firebaseui */

(function () {
    const configScript = document.getElementById("identity-platform-config");
    if (!configScript || typeof firebase === "undefined" || typeof firebaseui === "undefined") {
        return;
    }

    const config = JSON.parse(configScript.textContent);
    const existingApp = firebase.apps.find((app) => app.name === "[DEFAULT]");
    const app =
        existingApp ||
        firebase.initializeApp({
            apiKey: config.apiKey,
            authDomain: config.authDomain,
            projectId: config.projectId,
        });
    const auth = app.auth();
    const ui = firebaseui.auth.AuthUI.getInstance() || new firebaseui.auth.AuthUI(auth);
    const loader = document.getElementById("identity-auth-loader");

    let handlingAuthState = false;
    let pendingTotpSecret = null;
    let pendingResolver = null;
    let pendingVerificationEmail = "";

    const sections = {
        auth: document.getElementById("identity-auth-section"),
        verifyEmail: document.getElementById("identity-verify-email-section"),
        enrollTotp: document.getElementById("identity-totp-enrollment-section"),
        signinTotp: document.getElementById("identity-totp-signin-section"),
    };
    const banner = document.getElementById("auth-banner");

    function setVisibleSection(key) {
        Object.values(sections).forEach((section) => section.classList.remove("visible"));
        let targetSection = null;
        switch (key) {
            case "auth":
                targetSection = sections.auth;
                break;
            case "verifyEmail":
                targetSection = sections.verifyEmail;
                break;
            case "enrollTotp":
                targetSection = sections.enrollTotp;
                break;
            case "signinTotp":
                targetSection = sections.signinTotp;
                break;
            default:
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
        window.location.assign(body.redirect_url || config.dashboardUrl);
    }

    async function sendVerification(user) {
        await user.sendEmailVerification({
            url: config.verificationContinueUrl,
            handleCodeInApp: false,
        });
        pendingVerificationEmail = user.email || "";
        await auth.signOut();
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
            await user.reload();

            if (!isAllowedEmail(user.email || "")) {
                await auth.signOut();
                throw new Error(`Only approved ${config.allowedEmailDomain} users may access the corporate portal.`);
            }

            if (!user.emailVerified) {
                await sendVerification(user);
                if (isNewUser) {
                    showBanner("success", "Verify your corporate email to finish activating your account.");
                }
                return;
            }

            const factors = user.multiFactor.enrolledFactors;
            if (!factors.length) {
                await startTotpEnrollment(user, "");
                return;
            }

            await exchangeSession(user);
        } catch (error) {
            console.error(error);
            showBanner("error", error.message || "Unable to complete sign-in.");
            setVisibleSection("auth");
            startFirebaseUi();
        } finally {
            handlingAuthState = false;
        }
    }

    async function startTotpEnrollment(user, message) {
        const multiFactorSession = await user.multiFactor.getSession();
        pendingTotpSecret = await firebase.auth.TotpMultiFactorGenerator.generateSecret(multiFactorSession);

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
            const assertion = firebase.auth.TotpMultiFactorGenerator.assertionForEnrollment(pendingTotpSecret, code);
            await auth.currentUser.multiFactor.enroll(assertion, config.totpDisplayName);
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
                (candidate) => candidate.factorId === firebase.auth.TotpMultiFactorGenerator.FACTOR_ID
            );
            if (!hint) {
                throw new Error("No enrolled TOTP factor is available for sign-in.");
            }

            const assertion = firebase.auth.TotpMultiFactorGenerator.assertionForSignIn(hint.uid, code);
            const userCredential = await pendingResolver.resolveSignIn(assertion);
            pendingResolver = null;
            await handleAuthenticatedUser(userCredential.user, false);
        } catch (error) {
            console.error(error);
            showBanner("error", error.message || "Unable to complete MFA sign-in.");
        }
    }

    function startFirebaseUi() {
        setVisibleSection("auth");
        ui.reset();
        ui.start("#firebaseui-auth-container", {
            signInFlow: "popup",
            credentialHelper: firebaseui.auth.CredentialHelper.NONE,
            signInOptions: [
                {
                    provider: firebase.auth.EmailAuthProvider.PROVIDER_ID,
                    requireDisplayName: false,
                },
            ],
            callbacks: {
                signInSuccessWithAuthResult: (authResult) => {
                    void handleAuthenticatedUser(
                        authResult.user,
                        Boolean(authResult.additionalUserInfo && authResult.additionalUserInfo.isNewUser)
                    );
                    return false;
                },
                signInFailure: (error) => {
                    if (error && error.code === "auth/multi-factor-auth-required" && error.resolver) {
                        pendingResolver = error.resolver;
                        document.getElementById("identity-totp-signin-code").value = "";
                        clearBanner();
                        setVisibleSection("signinTotp");
                        return Promise.resolve();
                    }

                    console.error(error);
                    showBanner("error", (error && error.message) || "Unable to sign in.");
                    setVisibleSection("auth");
                    return Promise.resolve();
                },
                uiShown: () => {
                    if (loader) {
                        loader.style.display = "none";
                    }
                },
            },
            tosUrl: config.loginUrl,
            privacyPolicyUrl: () => window.location.assign(config.loginUrl),
        });
    }

    void auth.setPersistence(firebase.auth.Auth.Persistence.SESSION);
    auth.onAuthStateChanged((user) => {
        if (user) {
            void handleAuthenticatedUser(user, false);
        }
    });

    document.getElementById("identity-totp-enrollment-submit").addEventListener("click", () => {
        void completeTotpEnrollment();
    });
    document.getElementById("identity-totp-signin-submit").addEventListener("click", () => {
        void completeTotpSignIn();
    });
    document.getElementById("identity-back-to-login").addEventListener("click", () => {
        clearBanner();
        startFirebaseUi();
    });

    startFirebaseUi();
})();
