/**
 * Bootstraps DashboardManager from the page-embedded #dashboard-config payload.
 *
 * Extracted from the inline <script> in
 * templates/mission_control/dashboard.html so the template stays within
 * SonarCloud's Web:LongJavaScriptCheck limit. Load after the dashboard-* class
 * chain scripts.
 */

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('dashboard-config');
    if (!configEl) return;
    const dashboard = new globalThis.DashboardManager(JSON.parse(configEl.textContent));
    dashboard.init();
});
