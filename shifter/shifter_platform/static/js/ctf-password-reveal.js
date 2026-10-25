/**
 * Progressive show/hide toggle for CTF password inputs.
 *
 * Adds an eye button beside every ``input[type="password"]`` on the page so a
 * participant can reveal what they are typing and hide it again. Pure
 * enhancement: with JavaScript disabled the field stays a normal masked input.
 * CSP-safe (no inline handlers; wired with addEventListener).
 */

const EYE_ICON =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>';

const EYE_OFF_ICON =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24' +
    'A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>' +
    '<line x1="1" y1="1" x2="23" y2="23"/></svg>';

const SHOW_LABEL = 'Show password';
const HIDE_LABEL = 'Hide password';

function attachToggle(input) {
    if (input.dataset.revealWired === '1') {
        return;
    }
    input.dataset.revealWired = '1';

    const wrap = document.createElement('div');
    wrap.className = 'ctf-password-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ctf-reveal-toggle';
    button.setAttribute('aria-label', SHOW_LABEL);
    button.setAttribute('aria-pressed', 'false');
    button.innerHTML = EYE_ICON;
    wrap.appendChild(button);

    button.addEventListener('click', () => {
        const reveal = input.type === 'password';
        input.type = reveal ? 'text' : 'password';
        button.setAttribute('aria-pressed', reveal ? 'true' : 'false');
        button.setAttribute('aria-label', reveal ? HIDE_LABEL : SHOW_LABEL);
        button.innerHTML = reveal ? EYE_OFF_ICON : EYE_ICON;
        input.focus();
    });
}

function initPasswordReveal() {
    document.querySelectorAll('input[type="password"]').forEach(attachToggle);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPasswordReveal);
} else {
    initPasswordReveal();
}
