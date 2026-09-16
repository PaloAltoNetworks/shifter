// Tests for the event force-delete confirmation gate. The module wires an
// input listener that enables the delete button only when the typed text
// matches the expected event name (read from data-expected-name).

const fullMarkup = () => `
    <input id="confirmation-name" data-expected-name="My Event">
    <button id="delete-btn" disabled></button>
`;

function loadWith(html) {
    jest.resetModules();
    document.body.innerHTML = html;
    return require('./event_force_delete.js');
}

describe('event_force_delete', () => {
    afterEach(() => {
        jest.resetModules();
    });

    test('enables the delete button only when the typed name matches', () => {
        loadWith(fullMarkup());
        const input = document.getElementById('confirmation-name');
        const btn = document.getElementById('delete-btn');

        input.value = 'My Event';
        input.dispatchEvent(new Event('input'));
        expect(btn.disabled).toBe(false);

        input.value = 'Wrong Name';
        input.dispatchEvent(new Event('input'));
        expect(btn.disabled).toBe(true);
    });

    test('returns early without throwing when the elements are absent', () => {
        const mod = loadWith('<div></div>');
        expect(() => mod.initEventForceDelete()).not.toThrow();
    });

    test('binds on DOMContentLoaded when the document is still loading', () => {
        jest.resetModules();
        Object.defineProperty(document, 'readyState', {
            configurable: true,
            get: () => 'loading',
        });
        try {
            document.body.innerHTML = fullMarkup();
            require('./event_force_delete.js');
            document.dispatchEvent(new Event('DOMContentLoaded'));

            const input = document.getElementById('confirmation-name');
            const btn = document.getElementById('delete-btn');
            input.value = 'My Event';
            input.dispatchEvent(new Event('input'));
            expect(btn.disabled).toBe(false);
        } finally {
            delete document.readyState;
        }
    });
});
