/**
 * CTF password reveal toggle tests.
 */

function buildMarkup() {
    return `
        <form>
            <input id="id_password" name="password" type="password" value="hunter2">
        </form>
    `;
}

function loadModule() {
    jest.resetModules();
    document.body.innerHTML = buildMarkup();
    require('./ctf-password-reveal.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('ctf-password-reveal', () => {
    test('adds a toggle button beside a password input', () => {
        loadModule();
        const input = document.getElementById('id_password');
        const button = document.querySelector('.ctf-reveal-toggle');
        expect(button).not.toBeNull();
        expect(button.getAttribute('aria-pressed')).toBe('false');
        expect(button.getAttribute('aria-label')).toBe('Show password');
        expect(input.closest('.ctf-password-wrap')).not.toBeNull();
    });

    test('toggles the input between password and text', () => {
        loadModule();
        const input = document.getElementById('id_password');
        const button = document.querySelector('.ctf-reveal-toggle');

        expect(input.type).toBe('password');
        button.click();
        expect(input.type).toBe('text');
        expect(button.getAttribute('aria-pressed')).toBe('true');
        expect(button.getAttribute('aria-label')).toBe('Hide password');

        button.click();
        expect(input.type).toBe('password');
        expect(button.getAttribute('aria-pressed')).toBe('false');
        expect(button.getAttribute('aria-label')).toBe('Show password');
    });

    test('skips an input that is already wired', () => {
        jest.resetModules();
        document.body.innerHTML = `
            <form>
                <input id="plain" name="password" type="password">
                <input id="wired" name="confirm" type="password" data-reveal-wired="1">
            </form>
        `;
        require('./ctf-password-reveal.js');
        document.dispatchEvent(new Event('DOMContentLoaded'));
        expect(document.querySelectorAll('.ctf-reveal-toggle').length).toBe(1);
        expect(document.getElementById('plain').closest('.ctf-password-wrap')).not.toBeNull();
        expect(document.getElementById('wired').closest('.ctf-password-wrap')).toBeNull();
    });
});
