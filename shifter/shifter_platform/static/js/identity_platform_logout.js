import { initializeApp } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js";
import { getAuth, signOut } from "https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js";

(async function () {
    const configScript = document.getElementById("identity-platform-logout-config");
    if (!configScript) {
        window.location.assign("/");
        return;
    }

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
        window.location.assign(config.redirectUrl || "/");
    }
})();
