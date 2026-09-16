// Scenario editor list page: confirm before deleting a scenario.
//
// Extracted from the inline <script> block in
// templates/scenario_editor/list.html so the template stays within
// Sonar's Web:LongJavaScriptCheck limit.

document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-scenario-delete-btn").forEach(function (button) {
        button.addEventListener("click", function (event) {
            const scenarioName = button.dataset.scenarioName || "";
            if (!confirm("Delete scenario '" + scenarioName + "'? This cannot be undone.")) {
                event.preventDefault();
            }
        });
    });
});
