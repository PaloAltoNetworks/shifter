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

    function genericClientError(fallbackMessage) {
        return fallbackMessage || "Authentication is temporarily unavailable. Try again later.";
    }

    if (!configScript) {
        return;
    }

    (async function initializeIdentityPlatform() {
        let firebaseAppSdk;
        let firebaseAuthSdk;

        try {
            // Firebase TOTP MFA is only supported on the modular Web SDK, not
            // the compat bundle. Dynamic module imports from gstatic mirror the
            // existing logout path's trust model: TLS to Google's CDN rather than
            // per-dependency SRI on each imported module. If that tradeoff ever
            // becomes unacceptable, vendor the modular SDK under /static instead.
            [firebaseAppSdk, firebaseAuthSdk] = await Promise.all([
                import("https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js"),
                import("https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js"),
            ]);
        } catch (error) {
            console.error("Firebase SDK failed to load; sign-in is unavailable.", error);
            fatalBanner(
                "Authentication services could not load. Reload the page, and if the problem persists contact the Shifter operators."
            );
            disableForm();
            return;
        }

        const { getApps, initializeApp } = firebaseAppSdk;
        const {
            TotpMultiFactorGenerator,
            browserSessionPersistence,
            createUserWithEmailAndPassword,
            getAuth,
            getMultiFactorResolver,
            multiFactor,
            onAuthStateChanged,
            sendEmailVerification,
            sendPasswordResetEmail,
            setPersistence,
            signInWithEmailAndPassword,
            signOut,
        } = firebaseAuthSdk;

        const config = JSON.parse(configScript.textContent);
        const existingApp = getApps().find((candidate) => candidate.name === "[DEFAULT]");
        const app =
            existingApp ||
            initializeApp({
                apiKey: config.apiKey,
                authDomain: config.authDomain,
                projectId: config.projectId,
            });
        const auth = getAuth(app);
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
                case "auth/internal-error":
                    return genericClientError("Unable to continue authentication. Contact the Shifter operators.");
                default:
                    return null;
            }
        }

        function friendlyClientMessage(error, fallbackMessage) {
            const authMessage = friendlyAuthError(error);
            if (authMessage) {
                return authMessage;
            }
            return genericClientError(fallbackMessage);
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
                try {
                    await signOut(auth);
                } catch (signOutError) {
                    console.error("Failed to clear Firebase session after exchange error", signOutError);
                }
                throw new Error(body.message || "Authentication failed.");
            }
            window.location.assign(body.redirect_url || config.dashboardUrl);
        }

        async function sendVerification(user) {
            await sendEmailVerification(user, {
                url: config.verificationContinueUrl,
                handleCodeInApp: false,
            });
            pendingVerificationEmail = user.email || "";
            await signOut(auth);
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

                const factors = multiFactor(user).enrolledFactors;
                if (!factors.length) {
                    await startTotpEnrollment(user, "");
                    return;
                }

                await exchangeSession(user);
            } catch (error) {
                console.error(error);
                showBanner(
                    "error",
                    friendlyClientMessage(
                        error,
                        "Unable to complete sign-in. Try again or contact the Shifter operators."
                    )
                );
                setVisibleSection("auth");
                setAuthBusy(false);
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
                showBanner(
                    "error",
                    friendlyClientMessage(
                        error,
                        "Unable to finish MFA setup. Try again or contact the Shifter operators."
                    )
                );
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
                await pendingResolver.resolveSignIn(assertion);
                pendingResolver = null;
            } catch (error) {
                console.error(error);
                showBanner(
                    "error",
                    friendlyClientMessage(
                        error,
                        "Unable to complete MFA sign-in. Try again or contact the Shifter operators."
                    )
                );
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
                await signInWithEmailAndPassword(auth, email, password);
            } catch (error) {
                if (error && error.code === "auth/multi-factor-auth-required") {
                    pendingResolver = getMultiFactorResolver(auth, error);
                    document.getElementById("identity-totp-signin-code").value = "";
                    clearBanner();
                    setVisibleSection("signinTotp");
                    return;
                }
                console.error(error);
                showBanner(
                    "error",
                    friendlyClientMessage(error, "Unable to continue sign-in. Check your credentials and try again.")
                );
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
                await createUserWithEmailAndPassword(auth, email, password);
            } catch (error) {
                pendingIsNewUser = false;
                console.error(error);
                showBanner(
                    "error",
                    friendlyClientMessage(error, "Unable to create the account. Try again or contact the Shifter operators.")
                );
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
                await sendPasswordResetEmail(auth, email, {
                    url: config.verificationContinueUrl,
                    handleCodeInApp: false,
                });
                showBanner(
                    "success",
                    "If an account exists for that email, a password reset link has been sent."
                );
            } catch (error) {
                console.error(error);
                showBanner(
                    "error",
                    friendlyClientMessage(
                        error,
                        "Unable to request a password reset right now. Try again later."
                    )
                );
            } finally {
                setAuthBusy(false);
            }
        }

        await setPersistence(auth, browserSessionPersistence);

        onAuthStateChanged(auth, (user) => {
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
    })().catch((error) => {
        console.error("Identity Platform initialization failed", error);
        fatalBanner(
            "Authentication services could not load. Reload the page, and if the problem persists contact the Shifter operators."
        );
        disableForm();
    });
})();
