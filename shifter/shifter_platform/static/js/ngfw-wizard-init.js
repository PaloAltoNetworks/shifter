/* global NGFWWizardManager */
// Bootstraps the NGFW setup wizard on the wizard page.
//
// Extracted from the inline <script> block in
// templates/mission_control/ngfw/wizard.html so the template stays within
// Sonar's Web:LongJavaScriptCheck limit. The CSRF token is passed in via the
// #ngfw-wizard-config json_script payload; NGFWWizardManager is provided by
// ngfw.js.

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('ngfw-wizard-config');
    const config = configEl ? JSON.parse(configEl.textContent) : {};

    const wizard = new NGFWWizardManager({
        csrfToken: config.csrfToken,
        provisionUrl: '/api/v1/mission-control/ngfw/',
        detailUrlTemplate: '/mission-control/ngfw/{id}/'
    });
    wizard.init();

    // Debug helpers - call from console: debugShowSuccess() or debugGoToStep(4)
    globalThis.debugShowSuccess = function () { wizard.debugShowSuccess(); };
    globalThis.debugGoToStep = function (step) { wizard.debugGoToStep(step); };
});
