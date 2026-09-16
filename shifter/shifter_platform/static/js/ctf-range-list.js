/* global CTFRangeManager */
// CTF admin range-list bootstrap: instantiate the range manager and,
// when a provisioning run is active, start progress polling. Extracted
// from the inline <script> in templates/ctf/admin/range_list.html so
// the template stays within Sonar Web:LongJavaScriptCheck limits.
// Behavior is unchanged; configuration is read from the
// #ctf-range-list-config element's data-* attributes.

document.addEventListener('DOMContentLoaded', function () {
    const cfg = document.getElementById('ctf-range-list-config').dataset;
    const manager = new CTFRangeManager({
        csrfToken: cfg.csrfToken,
        provisionAllUrl: cfg.provisionAllUrl,
        rangeListUrl: cfg.rangeListUrl,
        spareProvisionUrl: cfg.spareProvisionUrl,
    });
    manager.init();
    if (cfg.activeProvisioning === 'true') {
        manager.startProgressPolling();
    }
});
