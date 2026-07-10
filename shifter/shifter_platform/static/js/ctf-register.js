// CTF magic-link token exchange.
//
// The invite token rides in the URL fragment (#token=...), which the browser
// never sends to the server (SonarCloud pythonenterprise:S8435). This script
// reads the fragment, scrubs it from history, and POSTs the token to the
// CSRF-protected exchange endpoint, then navigates to the returned redirect.
(function () {
    "use strict";

    const statusEl = document.getElementById("ctf-register-status");
    const exchangeUrl = statusEl.dataset.exchangeUrl;

    function getCookie(name) {
        const value = "; " + document.cookie;
        const parts = value.split("; " + name + "=");
        if (parts.length === 2) {
            return parts.pop().split(";").shift();
        }
        return "";
    }

    function setStatus(message) {
        statusEl.textContent = message;
    }

    const params = new URLSearchParams(globalThis.location.hash.replace(/^#/, ""));
    const token = params.get("token");
    // Scrub the token from the address bar / history immediately so it cannot
    // be copied, leaked via Referer, or restored from the back button.
    globalThis.history.replaceState(null, "", globalThis.location.pathname);

    if (!token) {
        setStatus("Missing invite token.");
        return;
    }

    fetch(exchangeUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken")
        },
        body: JSON.stringify({ token: token })
    })
        .then(function (response) {
            return response.json().then(function (data) {
                return { ok: response.ok, data: data };
            });
        })
        .then(function (result) {
            if (result.ok && result.data.redirect) {
                globalThis.location.replace(result.data.redirect);
            } else {
                setStatus(result.data.error || "Unable to complete sign-in.");
            }
        })
        .catch(function () {
            setStatus("Unable to complete sign-in. Please try again.");
        });
})();
