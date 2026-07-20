/**
 * Cookie notice dismissal tests.
 */

const STORAGE_KEY = 'shifter.cookieNotice.dismissed.v1';

const buildNoticeMarkup = () => `
    <section id="cookie-notice" class="cookie-notice" hidden>
        <p>Strictly necessary browser storage is used for authentication and session behavior.</p>
        <a id="cookie-notice-privacy-link" href="/privacy/">Privacy notice</a>
        <button type="button" id="cookie-notice-dismiss">Dismiss</button>
    </section>
`;

function loadCookieNoticeModule() {
    jest.resetModules();
    document.body.innerHTML = buildNoticeMarkup();
    require('./cookie-notice.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('cookie-notice', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    test('shows notice when dismissal key is absent', () => {
        loadCookieNoticeModule();
        const notice = document.getElementById('cookie-notice');
        expect(notice.hidden).toBe(false);
    });

    test('hides notice when dismissal key is set', () => {
        localStorage.setItem(STORAGE_KEY, '1');
        loadCookieNoticeModule();
        const notice = document.getElementById('cookie-notice');
        expect(notice.hidden).toBe(true);
    });

    test('dismiss persists storage key and hides notice', () => {
        loadCookieNoticeModule();
        const privacyLink = document.getElementById('cookie-notice-privacy-link');
        expect(privacyLink.getAttribute('href')).toBe('/privacy/');
        document.getElementById('cookie-notice-dismiss').click();
        expect(localStorage.getItem(STORAGE_KEY)).toBe('1');
        expect(document.getElementById('cookie-notice').hidden).toBe(true);
        expect(privacyLink.getAttribute('href')).toBe('/privacy/');
    });
});
