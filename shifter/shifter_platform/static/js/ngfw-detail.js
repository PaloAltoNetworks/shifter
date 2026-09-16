/**
 * Mission Control - NGFW detail page.
 *
 * Refresh-status button (re-fetches the NGFW list then reloads) and the CLI
 * access button (exchanges a short-lived SSH URL and opens it in a new tab).
 *
 * Extracted from the inline <script> in
 * templates/mission_control/ngfw/detail.html so the template stays within
 * SonarCloud's Web:LongJavaScriptCheck limit. The refresh and SSH endpoint URLs
 * are read from the buttons' data-* attributes; the CSRF token is read from the
 * csrftoken cookie.
 */

function getCookie(name) {
    if (!document.cookie) {
        return null;
    }
    const prefix = name + '=';
    const match = document.cookie
        .split(';')
        .map(function (part) { return part.trim(); })
        .find(function (part) { return part.startsWith(prefix); });
    return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function initRefreshButton() {
    const refreshBtn = document.querySelector('.ngfw-refresh-btn');
    if (!refreshBtn) return;

    refreshBtn.addEventListener('click', async function () {
        const icon = this.querySelector('svg');

        // Spin animation
        icon.style.transition = 'transform 0.5s ease';
        icon.style.transform = 'rotate(360deg)';
        this.disabled = true;

        try {
            await fetch(refreshBtn.dataset.ngfwListUrl);
            // Reload page to show updated status
            globalThis.location.reload();
        } catch (err) {
            console.error('Refresh failed:', err);
        } finally {
            setTimeout(() => {
                icon.style.transform = 'rotate(0deg)';
                this.disabled = false;
            }, 500);
        }
    });
}

function initCliButton() {
    const cliBtn = document.getElementById('ngfw-cli-btn');
    if (!cliBtn) return;

    cliBtn.addEventListener('click', async function () {
        const btnText = this.querySelector('span');
        const originalText = btnText.textContent;

        // Disable button and show loading state
        this.disabled = true;
        btnText.textContent = 'Opening CLI...';

        try {
            const response = await fetch(cliBtn.dataset.sshUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'Content-Type': 'application/json',
                },
                // 10 second timeout for token exchange
                signal: AbortSignal.timeout(10000),
            });

            if (!response.ok) {
                let errorMsg = 'Failed to generate CLI URL';
                try {
                    const data = await response.json();
                    errorMsg = data.error || errorMsg;
                } catch {
                    // Response wasn't JSON, use status text
                    errorMsg = response.statusText || errorMsg;
                }
                throw new Error(errorMsg);
            }

            const data = await response.json();

            if (!data.url) {
                throw new Error('Server returned invalid response');
            }

            // Open in new tab and check if it was blocked. A real Window always
            // exposes a boolean `closed`, so `!popup` (blocked -> null) plus
            // `popup.closed` (opened-then-closed) fully cover the blocked cases;
            // a `=== undefined` third check would be dead code (javascript:S3403).
            const popup = globalThis.open(data.url, '_blank');
            if (!popup || popup.closed) {
                // Popup was blocked
                const popupMessage = [
                    'Popup blocked. Click OK to try again.',
                    '',
                    'Tip: Allow popups for this site to use CLI access.',
                ].join('\n');
                if (confirm(popupMessage)) {
                    globalThis.location.href = data.url;
                } else {
                    throw new Error('Popup blocked by browser');
                }
            }

            // Reset button after short delay
            setTimeout(() => {
                this.disabled = false;
                btnText.textContent = originalText;
            }, 1000);
        } catch (error) {
            console.error('Error opening NGFW CLI:', error);

            // User-friendly error messages
            let userMsg = error.message;
            if (error.name === 'AbortError' || error.name === 'TimeoutError') {
                userMsg = 'Request timed out. Please try again.';
            } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
                userMsg = 'Network error. Please check your connection and try again.';
            }

            alert('Error opening CLI:\n\n' + userMsg);

            // Reset button immediately on error
            this.disabled = false;
            btnText.textContent = originalText;
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initRefreshButton();
    initCliButton();
});
