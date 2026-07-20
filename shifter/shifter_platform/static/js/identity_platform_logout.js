import { initializeApp } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js";
import { getAuth, signOut } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js";

// Only a root-relative path ("/path") that is NOT protocol-relative ("//host")
// is allowed: this rejects absolute URLs, "javascript:" targets, and any
// off-origin destination, so the value handed to location.assign can never
// navigate (or script) off this origin. The injected config is trusted; this
// keeps an open redirect / DOM-XSS impossible even if it is tampered with.
// Mirrors identity_platform_auth.js's sameOriginPath (CodeQL js/xss-through-dom).
const SAFE_REDIRECT_PATH = /^\/(?!\/)[\w\-./~!$&'()*+,;=:@%?#[\]]*$/;
function sameOriginPath(candidate) {
    if (typeof candidate === "string" && SAFE_REDIRECT_PATH.test(candidate)) {
        return candidate;
    }
    return null;
}

// Sign the user out of Identity Platform, then navigate to a validated
// same-origin path. Wrapped in a function (rather than top-level await) so the
// module is importable under the jest/babel harness.
async function runLogout(config) {
    try {
        const app = initializeApp({
            apiKey: config.apiKey,
            authDomain: config.authDomain,
            projectId: config.projectId,
        });
        await signOut(getAuth(app));
    } catch (error) {
        console.error("Identity Platform logout failed", error);
    } finally {
        globalThis.location.assign(sameOriginPath(config.redirectUrl) || "/");
    }
}

const configScript = document.getElementById("identity-platform-logout-config");

if (configScript) {
    // This `<script type="module">` entry point is transpiled to CommonJS by the
    // jsdom test harness, which cannot represent top-level await, so S7785
    // (prefer top-level await) is unsatisfiable here without breaking the suite.
    runLogout(JSON.parse(configScript.textContent)); // NOSONAR
} else {
    globalThis.location.assign("/");
}

export { runLogout, sameOriginPath };
