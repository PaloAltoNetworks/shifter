// NGFW deprovision confirmation + destroy. Extracted from the inline
// <script> in templates/mission_control/ngfw/deprovision.html so the
// template stays within Sonar Web:LongJavaScriptCheck limits. Behavior
// is unchanged; the CSRF token, NGFW id/name, and list URL are read
// from the deprovision button's data-* attributes.

function initNgfwDeprovision() {
    const confirmInput = document.getElementById('confirm-input');
    const deprovisionBtn = document.getElementById('deprovision-btn');
    if (!confirmInput || !deprovisionBtn) return;

    const csrfToken = deprovisionBtn.dataset.csrfToken;
    const ngfwId = deprovisionBtn.dataset.ngfwId;
    const ngfwName = deprovisionBtn.dataset.ngfwName;
    const listUrl = deprovisionBtn.dataset.listUrl;

    // Enable button when name matches
    confirmInput.addEventListener('input', function () {
        const matches = this.value.trim() === ngfwName;
        deprovisionBtn.disabled = !matches;
    });

    // Handle deprovision
    deprovisionBtn.addEventListener('click', function () {
        if (confirmInput.value.trim() !== ngfwName) {
            return;
        }

        deprovisionBtn.disabled = true;
        deprovisionBtn.textContent = 'Deprovisioning...';

        fetch(`/api/v1/mission-control/ngfw/${ngfwId}/destroy/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                confirm_name: confirmInput.value.trim()
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                deprovisionBtn.disabled = false;
                deprovisionBtn.textContent = 'Deprovision NGFW';
            } else {
                // Redirect to list page
                globalThis.location.href = listUrl;
            }
        })
        .catch(() => {
            alert('An error occurred. Please try again.');
            deprovisionBtn.disabled = false;
            deprovisionBtn.textContent = 'Deprovision NGFW';
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNgfwDeprovision);
} else {
    initNgfwDeprovision();
}
