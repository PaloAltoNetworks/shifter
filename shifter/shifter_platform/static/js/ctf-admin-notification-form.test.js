/**
 * CTF admin notification compose form tests.
 *
 * The module runs at load time and wires two handlers: a toggle button that
 * shows/hides the schedule field, and a form submit handler that injects a
 * hidden "action=schedule" input when the schedule field is visible (unless the
 * "send now" button was the submitter).
 */

function buildMarkup() {
    document.body.innerHTML = `
        <button id="btn-toggle-schedule">Schedule</button>
        <div id="schedule-group" class="d-none"></div>
        <form>
            <button type="submit" name="action" value="send_now">Send now</button>
            <button type="submit" name="action" value="schedule">Schedule now</button>
        </form>
    `;
}

function loadModule() {
    jest.resetModules();
    require('./ctf-admin-notification-form.js');
}

function submitWith(submitter) {
    const ev = new Event('submit', { bubbles: true, cancelable: true });
    Object.defineProperty(ev, 'submitter', { configurable: true, value: submitter });
    document.querySelector('form').dispatchEvent(ev);
    return ev;
}

describe('ctf-admin-notification-form', () => {
    beforeEach(() => {
        buildMarkup();
        loadModule();
    });

    describe('schedule toggle', () => {
        test('reveals the schedule group and relabels the toggle', () => {
            const toggle = document.getElementById('btn-toggle-schedule');
            const group = document.getElementById('schedule-group');

            toggle.click();

            expect(group.classList.contains('d-none')).toBe(false);
            expect(toggle.textContent).toBe('Cancel Schedule');
        });

        test('hides the schedule group again on a second click', () => {
            const toggle = document.getElementById('btn-toggle-schedule');
            const group = document.getElementById('schedule-group');

            toggle.click();
            toggle.click();

            expect(group.classList.contains('d-none')).toBe(true);
            expect(toggle.textContent).toBe('Schedule');
        });
    });

    describe('submit handling', () => {
        test('does not inject a hidden action when the schedule group is hidden', () => {
            submitWith(null);

            expect(document.querySelector('input[type="hidden"][name="action"]')).toBeNull();
        });

        test('does not inject a hidden action when send_now is the submitter', () => {
            document.getElementById('btn-toggle-schedule').click(); // reveal schedule group
            const sendNow = document.querySelector('button[value="send_now"]');

            submitWith(sendNow);

            expect(document.querySelector('input[type="hidden"][name="action"]')).toBeNull();
        });

        test('injects a hidden action=schedule input for a scheduled submit', () => {
            document.getElementById('btn-toggle-schedule').click(); // reveal schedule group
            const scheduleBtn = document.querySelector('button[value="schedule"]');

            submitWith(scheduleBtn);

            const hidden = document.querySelector('input[type="hidden"][name="action"]');
            expect(hidden).not.toBeNull();
            expect(hidden.value).toBe('schedule');
        });
    });
});
