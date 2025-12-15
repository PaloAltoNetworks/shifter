/* Cortex XDR Sidebar - Minimal JS */
document.addEventListener('DOMContentLoaded', function() {
    // Secondary panel toggle (if needed in future)
    const navItems = document.querySelectorAll('.nav-menu-item[data-panel]');
    const panels = document.querySelectorAll('.secondary-panel');

    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            const panelId = this.dataset.panel;
            if (panelId) {
                e.preventDefault();
                panels.forEach(p => p.classList.remove('open'));
                const panel = document.getElementById(panelId);
                if (panel) panel.classList.add('open');
            }
        });
    });
});
