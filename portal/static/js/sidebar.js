/**
 * Cortex XDR Sidebar JavaScript
 *
 * Handles:
 * - Secondary panel expand/collapse
 * - User avatar dropdown
 * - Outside click detection
 */

(function() {
    'use strict';

    // Secondary Panel Toggle
    function initSecondaryPanel() {
        const panelTriggers = document.querySelectorAll('[data-panel-trigger]');
        const secondaryPanel = document.getElementById('secondary-panel');
        const layout = document.querySelector('.layout');

        if (!secondaryPanel) return;

        panelTriggers.forEach(trigger => {
            trigger.addEventListener('click', function(e) {
                e.preventDefault();
                const panelId = this.getAttribute('data-panel-trigger');

                // Toggle panel
                if (secondaryPanel.classList.contains('open')) {
                    closeSecondaryPanel();
                } else {
                    openSecondaryPanel();
                }
            });
        });

        // Close on outside click
        document.addEventListener('click', function(e) {
            if (!secondaryPanel.contains(e.target) &&
                !e.target.closest('[data-panel-trigger]') &&
                secondaryPanel.classList.contains('open')) {
                closeSecondaryPanel();
            }
        });

        function openSecondaryPanel() {
            secondaryPanel.classList.add('open');
            if (layout) layout.classList.add('panel-open');
        }

        function closeSecondaryPanel() {
            secondaryPanel.classList.remove('open');
            if (layout) layout.classList.remove('panel-open');
        }
    }

    // User Avatar Dropdown
    function initUserDropdown() {
        const avatar = document.querySelector('.user-avatar');
        const dropdown = document.querySelector('.user-dropdown');

        if (!avatar || !dropdown) return;

        avatar.addEventListener('click', function(e) {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        // Close on outside click
        document.addEventListener('click', function(e) {
            if (!dropdown.contains(e.target) && !avatar.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                dropdown.classList.remove('open');
            }
        });
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        initSecondaryPanel();
        initUserDropdown();
    }
})();
