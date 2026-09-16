// Tests for the CTF admin event create/edit form: field collection,
// client-side validation, submit (create/edit), scenario dropdown loading,
// and edit-mode pre-population from the API.

const eventForm = require('./event-form.js');

const CHECKBOX_FIELDS = ['auto_cleanup', 'scoreboard_visible', 'team_mode', 'ngfw_enabled'];

function buildFormMarkup(scenarios, configOverrides) {
    const cfg = Object.assign(
        { isEdit: 'false', csrfToken: 'tok', apiUrl: '/api/event', eventId: '' },
        configOverrides || {}
    );
    const fields = eventForm.FIELDS.map((name) => {
        const input = CHECKBOX_FIELDS.includes(name)
            ? `<input type="checkbox" id="field-${name}">`
            : `<input id="field-${name}">`;
        return `${input}<span id="error-${name}"></span>`;
    }).join('');
    return `
        <div id="event-form-config"
             data-is-edit="${cfg.isEdit}"
             data-csrf-token="${cfg.csrfToken}"
             data-api-url="${cfg.apiUrl}"
             data-event-id="${cfg.eventId}"></div>
        <div id="form-alert"></div>
        <button id="submit-btn"></button>
        <div id="cooldown-group"></div>
        ${fields}
        <ul id="scenario-items"></ul>
        <div id="scenario-dropdown"></div>
        <script type="application/json" id="scenarios-data">${JSON.stringify(scenarios || [])}</script>
    `;
}

function fillValidForm() {
    document.getElementById('field-name').value = 'My Event';
    document.getElementById('field-event_start').value = '2026-01-01T10:00';
    document.getElementById('field-event_end').value = '2026-01-02T10:00';
}

function makeState(configOverrides) {
    return {
        config: Object.assign(
            { isEdit: false, csrfToken: 'tok', apiUrl: '/api/event', eventId: null },
            configOverrides || {}
        ),
        submitBtn: document.getElementById('submit-btn'),
        scenarioDropdown: null,
    };
}

describe('event-form', () => {
    beforeEach(() => {
        document.body.innerHTML = buildFormMarkup([{ id: 's1', name: 'Scenario One' }]);
        // jsdom does not implement scrollIntoView.
        Element.prototype.scrollIntoView = jest.fn();
        globalThis.ShifterDropdown = { init: jest.fn(() => ({ setValue: jest.fn() })) };
        globalThis.fetch = jest.fn();
    });

    describe('datetime helpers', () => {
        test('toISODatetime appends seconds only to 16-char values', () => {
            expect(eventForm.toISODatetime('')).toBeNull();
            expect(eventForm.toISODatetime('2026-01-01T10:00')).toBe('2026-01-01T10:00:00');
            expect(eventForm.toISODatetime('2026-01-01T10:00:30')).toBe('2026-01-01T10:00:30');
        });

        test('toDatetimeLocal truncates to minute precision', () => {
            expect(eventForm.toDatetimeLocal('')).toBe('');
            expect(eventForm.toDatetimeLocal('2026-01-01T10:00:00Z')).toBe('2026-01-01T10:00');
        });

        test('parseIntField reads integers and falls back when empty', () => {
            document.getElementById('field-range_spinup_minutes').value = '45';
            expect(eventForm.parseIntField('range_spinup_minutes', 30)).toBe(45);
            document.getElementById('field-range_spinup_minutes').value = '';
            expect(eventForm.parseIntField('range_spinup_minutes', 30)).toBe(30);
        });
    });

    describe('collectFormData', () => {
        test('reads text, checkbox, and integer fields into the payload', () => {
            fillValidForm();
            document.getElementById('field-range_spinup_minutes').value = '45';
            document.getElementById('field-max_participants').value = '';
            document.getElementById('field-team_mode').checked = true;
            document.getElementById('field-ngfw_enabled').checked = true;
            document.getElementById('field-attempt_limit_mode').value = 'timeout';

            const data = eventForm.collectFormData();

            expect(data.name).toBe('My Event');
            expect(data.event_start).toBe('2026-01-01T10:00:00');
            expect(data.event_end).toBe('2026-01-02T10:00:00');
            expect(data.range_spinup_minutes).toBe(45);
            expect(data.cleanup_delay_hours).toBe(0);
            expect(data.max_participants).toBeNull();
            expect(data.team_mode).toBe(true);
            expect(data.attempt_limit_mode).toBe('timeout');
            expect(data.attempt_limit_cooldown_seconds).toBe(300);
            expect(data.range_config).toEqual({ ngfw_enabled: true });
        });
    });

    describe('validate', () => {
        test('flags missing required fields and shows the summary alert', () => {
            const ok = eventForm.validate({ name: '', event_start: null, event_end: null });
            expect(ok).toBe(false);
            expect(document.getElementById('error-name').textContent).toContain('required');
            expect(document.getElementById('error-event_start').textContent).toContain('required');
            expect(document.getElementById('error-event_end').textContent).toContain('required');
            expect(document.getElementById('form-alert').textContent).toContain('fix the errors');
        });

        test('flags end before start and a late registration deadline', () => {
            const ok = eventForm.validate({
                name: 'x',
                event_start: '2026-01-02T00:00:00',
                event_end: '2026-01-01T00:00:00',
                registration_deadline: '2026-01-03T00:00:00',
            });
            expect(ok).toBe(false);
            expect(document.getElementById('error-event_end').textContent).toContain('after event start');
            expect(document.getElementById('error-registration_deadline').textContent).toContain('before event start');
        });

        test('enforces team size limits when team mode is enabled', () => {
            const ok = eventForm.validate({
                name: 'x',
                event_start: '2026-01-01T00:00:00',
                event_end: '2026-01-02T00:00:00',
                team_mode: true,
                team_size_limit: 1,
            });
            expect(ok).toBe(false);
            expect(document.getElementById('error-team_size_limit').textContent).toContain('between 2 and 10');
        });

        test('flags a freeze time before event start', () => {
            const ok = eventForm.validate({
                name: 'x',
                event_start: '2026-01-02T00:00:00',
                event_end: '2026-01-05T00:00:00',
                scoreboard_freeze_at: '2026-01-01T00:00:00',
            });
            expect(ok).toBe(false);
            expect(document.getElementById('error-scoreboard_freeze_at').textContent).toContain('after event start');
        });

        test('passes for a well-formed event', () => {
            const ok = eventForm.validate({
                name: 'x',
                event_start: '2026-01-01T00:00:00',
                event_end: '2026-01-02T00:00:00',
            });
            expect(ok).toBe(true);
        });
    });

    describe('validateScoreboardFreeze', () => {
        test('flags a freeze time at or after event end', () => {
            const ok = eventForm.validateScoreboardFreeze({
                event_end: '2026-01-02T00:00:00',
                scoreboard_freeze_at: '2026-01-03T00:00:00',
            });
            expect(ok).toBe(false);
        });
    });

    describe('toggleCooldownVisibility', () => {
        test('shows the group only in timeout mode', () => {
            const group = document.getElementById('cooldown-group');

            document.getElementById('field-attempt_limit_mode').value = 'timeout';
            eventForm.toggleCooldownVisibility();
            expect(group.style.display).toBe('');

            document.getElementById('field-attempt_limit_mode').value = 'lockout';
            eventForm.toggleCooldownVisibility();
            expect(group.style.display).toBe('none');
        });
    });

    describe('loadScenarios', () => {
        test('clears stale items, adds a None option, and initializes the dropdown', () => {
            document.getElementById('scenario-items').innerHTML = '<li>stale</li>';

            const dropdown = eventForm.loadScenarios();

            const items = document.querySelectorAll('#scenario-items li');
            expect(items.length).toBe(2);
            expect(items[0].textContent).toBe('(None)');
            expect(items[1].textContent).toBe('Scenario One');
            expect(items[1].dataset.value).toBe('s1');
            expect(globalThis.ShifterDropdown.init).toHaveBeenCalled();
            expect(dropdown).not.toBeNull();
        });
    });

    describe('submitForm', () => {
        test('does nothing and returns undefined when validation fails', () => {
            const result = eventForm.submitForm(makeState());
            expect(result).toBeUndefined();
            expect(globalThis.fetch).not.toHaveBeenCalled();
        });

        test('POSTs the payload and navigates on success (create mode)', async () => {
            fillValidForm();
            globalThis.fetch.mockResolvedValue({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ id: 99 }),
            });
            const state = makeState();

            await eventForm.submitForm(state);

            expect(globalThis.fetch).toHaveBeenCalledWith(
                '/api/event',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': 'tok' },
                })
            );
            // Button was disabled and relabeled before the request fired.
            expect(state.submitBtn.textContent).toBe('Creating...');
        });

        test('maps field errors and re-enables the button on a 400 (edit mode)', async () => {
            fillValidForm();
            globalThis.fetch.mockResolvedValue({
                ok: false,
                status: 400,
                json: () => Promise.resolve({ error: 'Bad request', details: { field_errors: { name: 'already taken' } } }),
            });
            const state = makeState({ isEdit: true, eventId: '5' });

            await eventForm.submitForm(state);

            expect(document.getElementById('error-name').textContent).toBe('already taken');
            expect(document.getElementById('form-alert').textContent).toBe('Bad request');
            expect(state.submitBtn.disabled).toBe(false);
            expect(state.submitBtn.textContent).toBe('Save Changes');
        });

        test('shows a network error message when the request rejects', async () => {
            fillValidForm();
            globalThis.fetch.mockRejectedValue(new Error('offline'));
            const state = makeState();

            await eventForm.submitForm(state);

            expect(document.getElementById('form-alert').textContent).toContain('Network error: offline');
            expect(state.submitBtn.disabled).toBe(false);
            expect(state.submitBtn.textContent).toBe('Create Event');
        });
    });

    describe('handleSubmitResult', () => {
        test('shows a generic alert when the error response has no field errors', () => {
            eventForm.handleSubmitResult({ ok: false, data: {} }, makeState());
            expect(document.getElementById('form-alert').textContent).toBe('An error occurred.');
        });
    });

    describe('populateForm', () => {
        test('fills fields from the API and selects the scenario', async () => {
            const setValue = jest.fn();
            const state = makeState({ isEdit: true, eventId: '42' });
            state.scenarioDropdown = { setValue };
            globalThis.fetch.mockResolvedValue({
                json: () => Promise.resolve({
                    name: 'Loaded Event',
                    event_start: '2026-01-01T10:00:00Z',
                    scoreboard_visible: false,
                    team_mode: true,
                    scenario_id: 's1',
                    range_config: { ngfw_enabled: true },
                }),
            });

            await eventForm.populateForm(state);

            expect(globalThis.fetch).toHaveBeenCalledWith('/api/event', { headers: { 'X-CSRFToken': 'tok' } });
            expect(document.getElementById('field-name').value).toBe('Loaded Event');
            expect(document.getElementById('field-event_start').value).toBe('2026-01-01T10:00');
            expect(document.getElementById('field-scoreboard_visible').checked).toBe(false);
            expect(document.getElementById('field-team_mode').checked).toBe(true);
            expect(document.getElementById('field-ngfw_enabled').checked).toBe(true);
            expect(setValue).toHaveBeenCalledWith('s1');
        });

        test('shows an alert when loading the event fails', async () => {
            const state = makeState({ isEdit: true, eventId: '42' });
            globalThis.fetch.mockRejectedValue(new Error('nope'));

            await eventForm.populateForm(state);

            expect(document.getElementById('form-alert').textContent).toContain('Failed to load event data: nope');
        });
    });

    describe('initEventForm', () => {
        test('wires the submit button and loads scenarios in create mode', async () => {
            eventForm.initEventForm();

            const items = document.querySelectorAll('#scenario-items li');
            expect(items.length).toBe(2);

            fillValidForm();
            globalThis.fetch.mockResolvedValue({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ id: 7 }),
            });

            document.getElementById('submit-btn').click();
            await Promise.resolve();

            expect(globalThis.fetch).toHaveBeenCalledWith('/api/event', expect.objectContaining({ method: 'POST' }));
        });

        test('populates from the API in edit mode', async () => {
            document.body.innerHTML = buildFormMarkup([{ id: 's1', name: 'Scenario One' }], {
                isEdit: 'true',
                eventId: '42',
            });
            globalThis.fetch.mockResolvedValue({ json: () => Promise.resolve({ name: 'Edited' }) });

            eventForm.initEventForm();
            // Flush the fetch -> json -> applyEventToForm microtask chain.
            await new Promise((resolve) => setTimeout(resolve, 0));

            expect(globalThis.fetch).toHaveBeenCalledWith('/api/event', { headers: { 'X-CSRFToken': 'tok' } });
            expect(document.getElementById('field-name').value).toBe('Edited');
        });
    });
});
