/* global ShifterDropdown */
// CTF admin event create/edit form: field collection, client-side
// validation, submit, scenario dropdown population, and (in edit mode)
// pre-populating fields from the API. Extracted from the inline
// <script> in templates/ctf/admin/event_form.html so the template stays
// within Sonar Web:LongJavaScriptCheck and Web:FileLengthCheck limits.
// Behavior is unchanged; edit-mode/CSRF/API configuration is read from
// the #event-form-config element's data-* attributes and the scenario
// list from the #scenarios-data json_script block.

var FIELDS = [
    'name', 'description', 'event_start', 'event_end',
    'registration_deadline', 'scoreboard_visible', 'scoreboard_freeze_at', 'scenario_id',
    'range_spinup_minutes', 'auto_cleanup', 'ngfw_enabled',
    'cleanup_delay_hours', 'max_participants', 'team_mode',
    'team_size_limit', 'submission_cooldown_seconds',
    'attempt_limit_mode', 'attempt_limit_cooldown_seconds',
    'rating_visibility', 'scoring_mode'
];

// --- DOM helpers ---
function getField(name) {
    return document.getElementById('field-' + name);
}

function getError(name) {
    return document.getElementById('error-' + name);
}

function getAlertEl() {
    return document.getElementById('form-alert');
}

function readConfig() {
    var cfg = document.getElementById('event-form-config').dataset;
    return {
        isEdit: cfg.isEdit === 'true',
        csrfToken: cfg.csrfToken,
        apiUrl: cfg.apiUrl,
        eventId: cfg.eventId || null,
    };
}

function clearErrors() {
    var alertEl = getAlertEl();
    alertEl.textContent = '';
    alertEl.classList.remove('visible');
    FIELDS.forEach(function (name) {
        var el = getError(name);
        if (el) el.textContent = '';
    });
}

function toggleCooldownVisibility() {
    var mode = getField('attempt_limit_mode').value;
    var group = document.getElementById('cooldown-group');
    if (group) group.style.display = mode === 'timeout' ? '' : 'none';
}

function showFieldError(name, msg) {
    var el = getError(name);
    if (el) el.textContent = msg;
}

function showAlert(msg) {
    var alertEl = getAlertEl();
    alertEl.textContent = msg;
    alertEl.classList.add('visible');
    alertEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Convert a datetime-local value (YYYY-MM-DDTHH:MM) to ISO-8601
 * with seconds appended for Django parse_datetime.
 */
function toISODatetime(val) {
    if (!val) return null;
    return val.length === 16 ? val + ':00' : val;
}

/**
 * Convert an ISO datetime string to datetime-local value (YYYY-MM-DDTHH:MM).
 */
function toDatetimeLocal(iso) {
    if (!iso) return '';
    return iso.substring(0, 16);
}

/**
 * Read an integer field's value, returning fallback when empty.
 */
function parseIntField(name, fallback) {
    var raw = getField(name).value;
    return raw ? Number.parseInt(raw, 10) : fallback;
}

// --- Build form data ---
function collectFormData() {
    var data = {
        name: getField('name').value.trim(),
        description: getField('description').value,
        event_start: toISODatetime(getField('event_start').value),
        event_end: toISODatetime(getField('event_end').value),
        auto_cleanup: getField('auto_cleanup').checked,
        scoreboard_visible: getField('scoreboard_visible').checked,
        team_mode: getField('team_mode').checked,
    };

    var regDeadline = getField('registration_deadline').value;
    data.registration_deadline = regDeadline ? toISODatetime(regDeadline) : null;

    var freezeAt = getField('scoreboard_freeze_at').value;
    data.scoreboard_freeze_at = freezeAt ? toISODatetime(freezeAt) : null;

    var scenarioId = getField('scenario_id').value;
    data.scenario_id = scenarioId || null;

    data.range_spinup_minutes = parseIntField('range_spinup_minutes', 30);
    data.cleanup_delay_hours = parseIntField('cleanup_delay_hours', 0);
    data.max_participants = parseIntField('max_participants', null);
    data.team_size_limit = parseIntField('team_size_limit', null);
    data.submission_cooldown_seconds = parseIntField('submission_cooldown_seconds', 0);

    data.attempt_limit_mode = getField('attempt_limit_mode').value;
    data.attempt_limit_cooldown_seconds = parseIntField('attempt_limit_cooldown_seconds', 300);

    data.rating_visibility = getField('rating_visibility').value;
    data.scoring_mode = getField('scoring_mode').value;

    // Pack ngfw_enabled into range_config
    data.range_config = {
        ngfw_enabled: getField('ngfw_enabled').checked,
    };

    return data;
}

// --- Client-side validation ---
function validateScoreboardFreeze(data) {
    var valid = true;
    if (data.event_start && data.scoreboard_freeze_at <= data.event_start) {
        showFieldError('scoreboard_freeze_at', 'Scoreboard freeze time must be after event start.');
        valid = false;
    }
    if (data.event_end && data.scoreboard_freeze_at >= data.event_end) {
        showFieldError('scoreboard_freeze_at', 'Scoreboard freeze time must be before event end.');
        valid = false;
    }
    return valid;
}

function validate(data) {
    clearErrors();
    var valid = true;

    if (!data.name) {
        showFieldError('name', 'Event name is required.');
        valid = false;
    }
    if (!data.event_start) {
        showFieldError('event_start', 'Event start is required.');
        valid = false;
    }
    if (!data.event_end) {
        showFieldError('event_end', 'Event end is required.');
        valid = false;
    }
    if (data.event_start && data.event_end && data.event_end <= data.event_start) {
        showFieldError('event_end', 'Event end must be after event start.');
        valid = false;
    }
    if (data.registration_deadline && data.event_start && data.registration_deadline >= data.event_start) {
        showFieldError('registration_deadline', 'Registration deadline must be before event start.');
        valid = false;
    }
    if (data.team_mode && (!data.team_size_limit || data.team_size_limit < 2 || data.team_size_limit > 10)) {
        showFieldError('team_size_limit', 'Team size must be between 2 and 10 when team mode is enabled.');
        valid = false;
    }
    if (data.scoreboard_freeze_at && !validateScoreboardFreeze(data)) {
        valid = false;
    }

    if (!valid) {
        showAlert('Please fix the errors below.');
    }
    return valid;
}

// --- Submit ---
function resetSubmitButton(state) {
    state.submitBtn.disabled = false;
    state.submitBtn.textContent = state.config.isEdit ? 'Save Changes' : 'Create Event';
}

function handleSubmitResult(result, state) {
    var config = state.config;
    if (result.ok) {
        var eventId = config.isEdit ? config.eventId : result.data.id;
        globalThis.location.href = '/ctf/admin/events/' + eventId + '/';
        return;
    }

    clearErrors();
    var errorMsg = result.data.error || 'An error occurred.';

    // Try to map field-specific errors
    var fieldErrors = result.data.details?.field_errors;
    if (fieldErrors) {
        Object.entries(fieldErrors).forEach(function (entry) {
            showFieldError(entry[0], entry[1]);
        });
    }

    showAlert(errorMsg);
    resetSubmitButton(state);
}

function submitForm(state) {
    var data = collectFormData();
    if (!validate(data)) return undefined;

    var config = state.config;
    state.submitBtn.disabled = true;
    state.submitBtn.textContent = config.isEdit ? 'Saving...' : 'Creating...';

    return fetch(config.apiUrl, {
        method: config.isEdit ? 'PUT' : 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': config.csrfToken,
        },
        body: JSON.stringify(data),
    })
    .then(function (resp) {
        return resp.json().then(function (json) {
            return { ok: resp.ok, status: resp.status, data: json };
        });
    })
    .then(function (result) {
        handleSubmitResult(result, state);
    })
    .catch(function (err) {
        clearErrors();
        showAlert('Network error: ' + err.message);
        resetSubmitButton(state);
    });
}

// --- Load scenarios into dropdown ---
function loadScenarios() {
    var scenarios = JSON.parse(document.getElementById('scenarios-data').textContent);
    var itemsEl = document.getElementById('scenario-items');

    // Clear existing items
    while (itemsEl.firstChild) {
        itemsEl.firstChild.remove();
    }

    // Add empty option
    var emptyLi = document.createElement('li');
    emptyLi.className = 'shifter-dropdown-item';
    emptyLi.dataset.value = '';
    emptyLi.textContent = '(None)';
    itemsEl.appendChild(emptyLi);

    scenarios.forEach(function (s) {
        var li = document.createElement('li');
        li.className = 'shifter-dropdown-item';
        li.dataset.value = s.id;
        li.textContent = s.name;
        itemsEl.appendChild(li);
    });

    // Initialize the dropdown
    return ShifterDropdown.init(document.getElementById('scenario-dropdown'));
}

// --- Edit mode: populate fields from API ---
function applyEventToForm(event, state) {
    getField('name').value = event.name || '';
    getField('description').value = event.description || '';
    getField('event_start').value = toDatetimeLocal(event.event_start);
    getField('event_end').value = toDatetimeLocal(event.event_end);
    getField('registration_deadline').value = toDatetimeLocal(event.registration_deadline);
    getField('scoreboard_visible').checked = event.scoreboard_visible !== false;
    getField('scoreboard_freeze_at').value = toDatetimeLocal(event.scoreboard_freeze_at);
    getField('range_spinup_minutes').value = event.range_spinup_minutes || 30;
    getField('auto_cleanup').checked = !!event.auto_cleanup;
    getField('cleanup_delay_hours').value = event.cleanup_delay_hours || 0;
    getField('max_participants').value = event.max_participants || '';
    getField('team_mode').checked = !!event.team_mode;
    getField('team_size_limit').value = event.team_size_limit || '';
    getField('submission_cooldown_seconds').value = event.submission_cooldown_seconds || 0;
    getField('attempt_limit_mode').value = event.attempt_limit_mode || 'lockout';
    getField('attempt_limit_cooldown_seconds').value = event.attempt_limit_cooldown_seconds || 300;
    getField('rating_visibility').value = event.rating_visibility || 'public';
    getField('scoring_mode').value = event.scoring_mode || 'standard';
    toggleCooldownVisibility();

    // ngfw_enabled from range_config
    var rc = event.range_config || {};
    getField('ngfw_enabled').checked = !!rc.ngfw_enabled;

    // Set scenario dropdown value
    if (event.scenario_id && state.scenarioDropdown) {
        state.scenarioDropdown.setValue(event.scenario_id);
    }
}

function populateForm(state) {
    return fetch(state.config.apiUrl, {
        headers: { 'X-CSRFToken': state.config.csrfToken },
    })
    .then(function (resp) { return resp.json(); })
    .then(function (event) { applyEventToForm(event, state); })
    .catch(function (err) {
        showAlert('Failed to load event data: ' + err.message);
    });
}

// --- Wiring ---
function initEventForm() {
    var state = {
        config: readConfig(),
        submitBtn: document.getElementById('submit-btn'),
        scenarioDropdown: null,
    };

    getField('attempt_limit_mode').addEventListener('change', toggleCooldownVisibility);
    toggleCooldownVisibility();

    state.submitBtn.addEventListener('click', function () {
        submitForm(state);
    });

    state.scenarioDropdown = loadScenarios();

    if (state.config.isEdit) {
        populateForm(state);
    }

    return state;
}

document.addEventListener('DOMContentLoaded', initEventForm);

// Expose for testing
if (typeof module !== 'undefined' && module.exports) { // eslint-disable-line no-undef
    module.exports = { // eslint-disable-line no-undef
        FIELDS: FIELDS,
        getField: getField,
        getError: getError,
        readConfig: readConfig,
        clearErrors: clearErrors,
        toggleCooldownVisibility: toggleCooldownVisibility,
        showFieldError: showFieldError,
        showAlert: showAlert,
        toISODatetime: toISODatetime,
        toDatetimeLocal: toDatetimeLocal,
        parseIntField: parseIntField,
        collectFormData: collectFormData,
        validateScoreboardFreeze: validateScoreboardFreeze,
        validate: validate,
        handleSubmitResult: handleSubmitResult,
        submitForm: submitForm,
        loadScenarios: loadScenarios,
        applyEventToForm: applyEventToForm,
        populateForm: populateForm,
        initEventForm: initEventForm,
    };
}
