/* global firebase */

(function () {
    const configScript = document.getElementById("identity-platform-config");
    const banner = document.getElementById("auth-banner");

    function fatalBanner(message) {
        if (!banner) {
            return;
        }
        banner.textContent = message;
        banner.className = "banner visible error";
    }

    function disableForm() {
        const formElements = [
            "identity-email",
            "identity-password",
            "identity-signin-submit",
            "identity-signup-submit",
            "identity-reset-password",
            "identity-totp-enrollment-submit",
            "identity-totp-signin-submit",
        ];
        formElements.forEach((id) => {
            const element = document.getElementById(id);
            if (element) {
                element.disabled = true;
            }
        });
    }

    if (!configScript) {
        return;
    }

    // Firebase load failures used to silently bail out, which left the sign-in
    // form alive but completely dead on click. Surface the failure explicitly so
    // a blocked CDN or bad SRI hash is not indistinguishable from a real bug.
    if (typeof firebase === "undefined") {
        console.error("Firebase SDK failed to load; sign-in is unavailable.");
        fatalBanner(
            "Authentication services could not load. Reload the page, and if the problem persists contact the Shifter operators."
        );
        disableForm();
        return;
    }

    (async function initializeIdentityPlatform() {
        const config = JSON.parse(configScript.textContent);
        const existingApp = firebase.apps.find((candidate) => candidate.name === "[DEFAULT]");
        const app =
            existingApp ||
            firebase.initializeApp({
                apiKey: config.apiKey,
                authDomain: config.authDomain,
                projectId: config.projectId,
            });
        const auth = app.auth();
        const authForm = document.getElementById("identity-auth-form");
        const emailInput = document.getElementById("identity-email");
        const passwordInput = document.getElementById("identity-password");
        const signInButton = document.getElementById("identity-signin-submit");
        const signUpButton = document.getElementById("identity-signup-submit");
        const resetPasswordButton = document.getElementById("identity-reset-password");

        let handlingAuthState = false;
        let pendingTotpSecret = null;
        let pendingResolver = null;
        let pendingVerificationEmail = "";
        // Tracks whether the next onAuthStateChanged firing is the result of a
        // self-service account creation, so handleAuthenticatedUser can show the
        // "check your inbox" banner exactly once. Cleared as soon as it is read.
        let pendingIsNewUser = false;

        const sections = {
            auth: document.getElementById("identity-auth-section"),
            verifyEmail: document.getElementById("identity-verify-email-section"),
            enrollTotp: document.getElementById("identity-totp-enrollment-section"),
            signinTotp: document.getElementById("identity-totp-signin-section"),
        };

        function currentEmail() {
            return String(emailInput.value || "").trim().toLowerCase();
        }

        function currentPassword() {
            return String(passwordInput.value || "");
        }

        function setAuthBusy(isBusy) {
            [emailInput, passwordInput, signInButton, signUpButton, resetPasswordButton].forEach((element) => {
                if (element) {
                    element.disabled = isBusy;
                }
            });
        }

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

        // Optimistic domain-only check for the Create Account button. The server-side
        // beforeCreate Cloud Function and IdentityPlatformBackend enforce the real
        // allow-list (domain + external whitelist), so this only exists to give PAN
        // users a faster error when they mistype. Whitelisted external users exist
        // server-side but are not exposed here — they must sign in with an existing
        // account rather than self-register.
        function isAllowedRegistrationEmail(email) {
            const normalized = String(email || "").trim().toLowerCase();
            if (!normalized) {
                return false;
            }
            return normalized.endsWith(`@${config.allowedEmailDomain}`);
        }

        function friendlyAuthError(error) {
            switch (error && error.code) {
                case "auth/invalid-email":
                    return "Enter a valid corporate email address.";
                case "auth/missing-email":
                    return "Corporate email is required.";
                case "auth/missing-password":
                    return "Password is required.";
                case "auth/invalid-credential":
                case "auth/wrong-password":
                case "auth/user-not-found":
                    return "Invalid email or password.";
                case "auth/email-already-in-use":
                    return "This email is already registered. Sign in or reset the password.";
                case "auth/weak-password":
                    return "Choose a stronger password.";
                case "auth/too-many-requests":
                    return "Too many attempts. Wait a moment and try again.";
                case "auth/admin-restricted-operation":
                    return "Account creation is not available for this email.";
                default:
                    return (error && error.message) || "Unable to complete authentication.";
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
                if (body.error === "email_verification_required") {
                    await sendVerification(user);
                    return;
                }
                if (body.error === "mfa_enrollment_required") {
                    await startTotpEnrollment(user, body.message);
                    return;
                }
                // Any other 4xx/5xx is non-retryable from the client's perspective
                // (domain rejection, revoked token, backend outage). Clear the Firebase
                // session before surfacing the error so onAuthStateChanged doesn't
                // immediately re-enter exchangeSession on the next tick and trap the
                // user in an infinite retry loop.
                try {
                    await auth.signOut();
                } catch (signOutError) {
                    console.error("Failed to clear Firebase session after exchange error", signOutError);
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
            passwordInput.value = "";
            document.getElementById("identity-verify-email-copy").textContent =
                `A verification email has been sent to ${pendingVerificationEmail}. Open the link in that email, then return here to sign in again.`;
            clearBanner();
            setVisibleSection("verifyEmail");
        }

        async function handleAuthenticatedUser(user) {
            if (!user || handlingAuthState) {
                return;
            }

            const wasNewUser = pendingIsNewUser;
            pendingIsNewUser = false;

            handlingAuthState = true;
            clearBanner();

            try {
                await user.reload();

                if (!user.emailVerified) {
                    await sendVerification(user);
                    if (wasNewUser) {
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
                setAuthBusy(false);
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
                // Firebase's multiFactor.enroll refreshes the ID token but does not
                // re-fire onAuthStateChanged (the user identity did not change), so
                // we have to drive the follow-on exchange directly rather than
                // relying on the state-change listener.
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
                // resolveSignIn installs the authenticated user on the default
                // Firebase app, which triggers onAuthStateChanged; the listener
                // below picks up the flow from there.
                await pendingResolver.resolveSignIn(assertion);
                pendingResolver = null;
            } catch (error) {
                console.error(error);
                showBanner("error", error.message || "Unable to complete MFA sign-in.");
            }
        }

        async function signInWithPassword() {
            const email = currentEmail();
            const password = currentPassword();
            if (!email) {
                showBanner("error", "Corporate email is required.");
                return;
            }
            if (!password) {
                showBanner("error", "Password is required.");
                return;
            }

            clearBanner();
            setAuthBusy(true);
            setVisibleSection("auth");
            try {
                // signInWithEmailAndPassword fires onAuthStateChanged on success;
                // handleAuthenticatedUser is driven from the state listener so we
                // don't race against a second firing on the same credential.
                await auth.signInWithEmailAndPassword(email, password);
            } catch (error) {
                if (error && error.code === "auth/multi-factor-auth-required" && error.resolver) {
                    pendingResolver = error.resolver;
                    document.getElementById("identity-totp-signin-code").value = "";
                    clearBanner();
                    setVisibleSection("signinTotp");
                    return;
                }
                console.error(error);
                showBanner("error", friendlyAuthError(error));
                setVisibleSection("auth");
            } finally {
                setAuthBusy(false);
            }
        }

        async function createAccount() {
            const email = currentEmail();
            const password = currentPassword();
            if (!email) {
                showBanner("error", "Corporate email is required.");
                return;
            }
            if (!isAllowedRegistrationEmail(email)) {
                showBanner("error", `Only approved ${config.allowedEmailDomain} users may register.`);
                return;
            }
            if (!password) {
                showBanner("error", "Password is required.");
                return;
            }

            clearBanner();
            setAuthBusy(true);
            setVisibleSection("auth");
            pendingIsNewUser = true;
            try {
                // createUserWithEmailAndPassword fires onAuthStateChanged on success.
                await auth.createUserWithEmailAndPassword(email, password);
            } catch (error) {
                pendingIsNewUser = false;
                console.error(error);
                showBanner("error", friendlyAuthError(error));
                setVisibleSection("auth");
            } finally {
                setAuthBusy(false);
            }
        }

        async function sendPasswordReset() {
            const email = currentEmail();
            if (!email) {
                showBanner("error", "Enter your corporate email before requesting a password reset.");
                return;
            }

            clearBanner();
            setAuthBusy(true);
            try {
                await auth.sendPasswordResetEmail(email, {
                    url: config.verificationContinueUrl,
                    handleCodeInApp: false,
                });
                showBanner(
                    "success",
                    "If an account exists for that email, a password reset link has been sent."
                );
            } catch (error) {
                console.error(error);
                showBanner("error", friendlyAuthError(error));
            } finally {
                setAuthBusy(false);
            }
        }

        // Persist the Firebase session only for the duration of the tab and
        // wait for that guarantee to install before wiring the state-change
        // listener. Otherwise a cached user from a prior page load can fire
        // handleAuthenticatedUser under an undefined persistence policy.
        await auth.setPersistence(firebase.auth.Auth.Persistence.SESSION);

        auth.onAuthStateChanged((user) => {
            if (user) {
                void handleAuthenticatedUser(user);
            }
        });

        authForm.addEventListener("submit", (event) => {
            event.preventDefault();
            void signInWithPassword();
        });
        signUpButton.addEventListener("click", () => {
            void createAccount();
        });
        resetPasswordButton.addEventListener("click", () => {
            void sendPasswordReset();
        });
        document.getElementById("identity-totp-enrollment-submit").addEventListener("click", () => {
            void completeTotpEnrollment();
        });
        document.getElementById("identity-totp-signin-submit").addEventListener("click", () => {
            void completeTotpSignIn();
        });
        document.getElementById("identity-back-to-login").addEventListener("click", () => {
            clearBanner();
            setVisibleSection("auth");
        });
    })();
})();
