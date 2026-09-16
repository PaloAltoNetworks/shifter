/**
 * Mission Control - credentials list page.
 *
 * Type filter tabs plus delete-with-confirmation for each credential.
 *
 * Extracted from the inline <script> in
 * templates/mission_control/credentials/list.html so the template stays within
 * SonarCloud's Web:LongJavaScriptCheck limit. The CSRF token is read from the
 * #mc-credentials-config JSON payload.
 */

function initFilterTabs() {
    document.querySelectorAll('.filter-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            const filter = this.dataset.filter;

            document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            document.querySelectorAll('tbody tr').forEach(function (row) {
                if (filter === 'all' || row.dataset.type === filter) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    });
}

function initDeleteButtons(csrfToken) {
    document.querySelectorAll('[data-action="delete"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const credId = this.dataset.credentialId;
            const credName = this.dataset.credentialName;

            if (!confirm(`Are you sure you want to delete "${credName}"? This cannot be undone.`)) {
                return;
            }

            fetch(`/api/v1/mission-control/credentials/${credId}/delete/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
            })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        alert(data.error);
                    } else {
                        globalThis.location.reload();
                    }
                })
                .catch(function () {
                    alert('An error occurred. Please try again.');
                });
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('mc-credentials-config');
    const csrfToken = configEl ? JSON.parse(configEl.textContent).csrfToken : '';

    initFilterTabs();
    initDeleteButtons(csrfToken);
});
