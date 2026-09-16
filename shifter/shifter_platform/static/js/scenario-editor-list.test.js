// Tests for the scenario editor list page: the delete buttons must ask for
// confirmation and cancel the default action (form submit / navigation) when
// the user declines.
//
// The module wires its listeners on DOMContentLoaded, so it is required once
// and each test rebuilds the DOM then dispatches DOMContentLoaded to re-wire
// against the fresh buttons.

require('./scenario-editor-list.js');

describe('scenario-editor-list', () => {
    let confirmSpy;

    beforeEach(() => {
        document.body.innerHTML = `
            <button class="js-scenario-delete-btn" data-scenario-name="Alpha"></button>
            <button class="js-scenario-delete-btn"></button>
        `;
        confirmSpy = jest.spyOn(globalThis, 'confirm').mockReturnValue(true);
        document.dispatchEvent(new Event('DOMContentLoaded'));
    });

    afterEach(() => {
        confirmSpy.mockRestore();
    });

    test('confirms with the scenario name and allows deletion when accepted', () => {
        const btn = document.querySelector('[data-scenario-name="Alpha"]');
        const evt = new Event('click', { bubbles: true, cancelable: true });

        btn.dispatchEvent(evt);

        expect(confirmSpy).toHaveBeenCalledWith("Delete scenario 'Alpha'? This cannot be undone.");
        expect(evt.defaultPrevented).toBe(false);
    });

    test('cancels the default action when the user declines', () => {
        confirmSpy.mockReturnValue(false);
        const btn = document.querySelector('[data-scenario-name="Alpha"]');
        const evt = new Event('click', { bubbles: true, cancelable: true });

        btn.dispatchEvent(evt);

        expect(evt.defaultPrevented).toBe(true);
    });

    test('falls back to an empty name when data-scenario-name is absent', () => {
        confirmSpy.mockReturnValue(false);
        const btn = document.querySelectorAll('.js-scenario-delete-btn')[1];
        const evt = new Event('click', { bubbles: true, cancelable: true });

        btn.dispatchEvent(evt);

        expect(confirmSpy).toHaveBeenCalledWith("Delete scenario ''? This cannot be undone.");
        expect(evt.defaultPrevented).toBe(true);
    });
});
