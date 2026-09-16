// NGFW list: per-card status refresh. Extracted from the inline
// <script> in templates/mission_control/ngfw/list.html so the template
// stays within Sonar Web:LongJavaScriptCheck limits. Behavior is
// unchanged; the list endpoint is read from the .ngfw-grid element's
// data-ngfw-list-url attribute.

function initNgfwList() {
    const grid = document.querySelector('.ngfw-grid');
    if (!grid) return;
    const listUrl = grid.dataset.ngfwListUrl;

    document.querySelectorAll('.ngfw-refresh-btn').forEach((btn) => {
        btn.addEventListener('click', async function () {
            const ngfwId = this.dataset.ngfwId;
            const icon = this.querySelector('svg');

            // Spin animation
            icon.style.transition = 'transform 0.5s ease';
            icon.style.transform = 'rotate(360deg)';
            this.disabled = true;

            try {
                const response = await fetch(listUrl);
                const data = await response.json();

                // Confirm this NGFW is present in the response
                const ngfwPresent = data.ngfws.some((n) => n.id === ngfwId);
                if (ngfwPresent) {
                    // Reload page to show updated status
                    globalThis.location.reload();
                }
            } catch (err) {
                console.error('Refresh failed:', err);
            } finally {
                setTimeout(() => {
                    icon.style.transform = 'rotate(0deg)';
                    this.disabled = false;
                }, 500);
            }
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNgfwList);
} else {
    initNgfwList();
}
