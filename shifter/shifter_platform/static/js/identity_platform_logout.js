import { initializeApp } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js";
import { getAuth, signOut } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js";

const configScript = document.getElementById("identity-platform-logout-config");

if (configScript) {
    const config = JSON.parse(configScript.textContent);

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
        globalThis.location.assign(config.redirectUrl || "/");
    }
} else {
    globalThis.location.assign("/");
}
