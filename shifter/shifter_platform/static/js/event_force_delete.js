// Event force-delete confirmation gate: enable the delete button only
// when the typed name matches the event name. Extracted from the
// inline <script> in templates/ctf/admin/event_force_delete.html so the
// template stays within Sonar Web:LongJavaScriptCheck limits. The
// expected name is read from the input's data-expected-name attribute.

function initEventForceDelete() {
    var input = document.getElementById('confirmation-name');
    var btn = document.getElementById('delete-btn');
    if (!input || !btn) return;
    var expectedName = input.dataset.expectedName;

    input.addEventListener('input', function () {
        btn.disabled = (input.value !== expectedName);
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEventForceDelete);
} else {
    initEventForceDelete();
}

// Expose for testing
if (typeof module !== 'undefined' && module.exports) { // eslint-disable-line no-undef
    module.exports = { initEventForceDelete: initEventForceDelete }; // eslint-disable-line no-undef
}
