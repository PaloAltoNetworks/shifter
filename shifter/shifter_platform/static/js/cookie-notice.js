/**
 * Dismissible strictly-necessary storage notice (client-local persistence only).
 */

const STORAGE_KEY = 'shifter.cookieNotice.dismissed.v1';

function initCookieNotice() {
    const notice = document.getElementById('cookie-notice');
    if (!notice) {
        return;
    }

    if (localStorage.getItem(STORAGE_KEY) === '1') {
        notice.hidden = true;
        return;
    }

    notice.hidden = false;

    const dismissButton = document.getElementById('cookie-notice-dismiss');
    if (!dismissButton) {
        return;
    }

    dismissButton.addEventListener('click', () => {
        localStorage.setItem(STORAGE_KEY, '1');
        notice.hidden = true;
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCookieNotice);
} else {
    initCookieNotice();
}
