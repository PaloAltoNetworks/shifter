// Tests for mc-settings.js — the Mission Control settings page delete-account
// confirmation modal.
//
// The module runs at load time (no DOMContentLoaded wrapper): it reads the modal
// elements and binds open/cancel/confirm-input handlers. The DOM fixture must
// exist before the module is required, so each scenario builds the fixture, then
// requires the module fresh via jest.resetModules().

function fixture() {
    return `
        <button id="delete-account-btn">Delete account</button>
        <div id="delete-modal" style="display: none;">
            <input id="delete-confirm-input" value="">
            <button id="cancel-delete-btn">Cancel</button>
            <button id="confirm-delete-btn" disabled>Confirm</button>
        </div>
    `;
}

function loadModule() {
    jest.resetModules();
    document.body.innerHTML = fixture();
    require('./mc-settings.js');
}

describe('mc-settings', () => {
    beforeEach(() => {
        loadModule();
    });

    test('the delete button opens the confirmation modal', () => {
        document.getElementById('delete-account-btn').click();

        expect(document.getElementById('delete-modal').style.display).toBe('flex');
    });

    test('cancel hides the modal, clears the input, and re-disables confirm', () => {
        const modal = document.getElementById('delete-modal');
        const input = document.getElementById('delete-confirm-input');
        const confirmBtn = document.getElementById('confirm-delete-btn');

        // Open + type a valid value + enable confirm first.
        document.getElementById('delete-account-btn').click();
        input.value = 'DELETE';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        expect(confirmBtn.disabled).toBe(false);

        document.getElementById('cancel-delete-btn').click();

        expect(modal.style.display).toBe('none');
        expect(input.value).toBe('');
        expect(confirmBtn.disabled).toBe(true);
    });

    test('confirm stays disabled until the input exactly matches DELETE', () => {
        const input = document.getElementById('delete-confirm-input');
        const confirmBtn = document.getElementById('confirm-delete-btn');

        input.value = 'delete';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        expect(confirmBtn.disabled).toBe(true);

        input.value = 'DELETE';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        expect(confirmBtn.disabled).toBe(false);
    });
});
