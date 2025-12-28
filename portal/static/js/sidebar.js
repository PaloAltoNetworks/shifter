/**
 * Cortex XDR Left Navigation - Direct port behavior
 */

document.addEventListener('DOMContentLoaded', function() {
    const leftNav = document.getElementById('leftNav');
    const lockBtn = document.getElementById('lockBtn');

    if (!leftNav || !lockBtn) return;

    // Get submenu elements
    const submenuPanel = document.getElementById('navSubmenuPanel');
    const submenuTitle = document.getElementById('navSubmenuTitle');
    const submenuItems = document.getElementById('navSubmenuItems');
    const backBtn = document.getElementById('navBackBtn');
    const submenuTriggers = document.querySelectorAll('.nav-submenu-trigger');

    // Track which submenu is currently active (persists across minimize/expand)
    let activeSubmenuId = leftNav.dataset.activeSubmenu || null;

    // Helper to open a submenu by ID
    function openSubmenu(submenuId) {
        const trigger = document.querySelector(`.nav-submenu-trigger[data-submenu="${submenuId}"]`);
        const template = document.getElementById('submenu-' + submenuId);

        if (trigger && template && submenuPanel) {
            // Set the title
            if (submenuTitle) {
                submenuTitle.textContent = trigger.getAttribute('data-submenu-title');
            }

            // Clear and populate submenu items
            if (submenuItems) {
                submenuItems.innerHTML = '';
                submenuItems.appendChild(template.content.cloneNode(true));
            }

            // Mark this trigger as active/open
            submenuTriggers.forEach(t => t.classList.remove('is-open'));
            trigger.classList.add('is-open');

            // Open the submenu panel
            leftNav.classList.add('submenu-open');
            activeSubmenuId = submenuId;
        }
    }

    // Helper to close submenu panel (visual only, keeps activeSubmenuId if on submenu page)
    function closeSubmenuPanel() {
        leftNav.classList.remove('submenu-open');
        submenuTriggers.forEach(t => t.classList.remove('is-open'));
    }

    // Check localStorage for lock state
    const isLocked = localStorage.getItem('nav-lock') === 'true';

    if (isLocked) {
        document.body.classList.add('nav-lock');
        leftNav.classList.remove('minimized');
        lockBtn.classList.add('active');
        lockBtn.setAttribute('aria-expanded', 'true');
    }

    // Auto-open submenu if we're on a submenu page
    if (activeSubmenuId && !leftNav.classList.contains('minimized')) {
        openSubmenu(activeSubmenuId);
    }

    // Expand on hover (if not locked)
    leftNav.addEventListener('mouseenter', function() {
        document.body.classList.remove('nav-mouse-leave');
        if (!document.body.classList.contains('nav-lock')) {
            leftNav.classList.remove('minimized');
            // Re-open submenu if we have an active one
            if (activeSubmenuId) {
                openSubmenu(activeSubmenuId);
            }
        }
    });

    // Collapse on mouse leave (if not locked)
    leftNav.addEventListener('mouseleave', function() {
        document.body.classList.add('nav-mouse-leave');
        if (!document.body.classList.contains('nav-lock')) {
            leftNav.classList.add('minimized');
            closeSubmenuPanel();
        }
    });

    // Lock button click
    lockBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();

        const willBeLocked = !document.body.classList.contains('nav-lock');

        if (willBeLocked) {
            document.body.classList.add('nav-lock');
            document.body.classList.remove('nav-mouse-leave');
            leftNav.classList.remove('minimized');
            lockBtn.classList.add('active');
            lockBtn.setAttribute('aria-expanded', 'true');
            localStorage.setItem('nav-lock', 'true');
            // Re-open submenu if we have an active one
            if (activeSubmenuId) {
                openSubmenu(activeSubmenuId);
            }
        } else {
            document.body.classList.remove('nav-lock');
            lockBtn.classList.remove('active');
            lockBtn.setAttribute('aria-expanded', 'false');
            localStorage.setItem('nav-lock', 'false');
        }
    });

    // Initial state - start with mouse leave (unless locked)
    if (!isLocked) {
        document.body.classList.add('nav-mouse-leave');
    }

    // Open submenu panel when clicking a submenu trigger
    submenuTriggers.forEach(trigger => {
        trigger.addEventListener('click', function(e) {
            e.preventDefault();
            const submenuId = this.getAttribute('data-submenu');
            openSubmenu(submenuId);
        });
    });

    // Close submenu panel when clicking back button
    if (backBtn) {
        backBtn.addEventListener('click', function(e) {
            e.preventDefault();
            closeSubmenuPanel();
            // Only clear activeSubmenuId if we're not on a submenu page
            if (!leftNav.dataset.activeSubmenu) {
                activeSubmenuId = null;
            }
        });
    }

    // Submenu lock button - same behavior as main lock button
    const submenuLockBtn = document.getElementById('submenuLockBtn');
    if (submenuLockBtn) {
        // Sync initial state
        if (isLocked) {
            submenuLockBtn.classList.add('active');
            submenuLockBtn.setAttribute('aria-expanded', 'true');
        }

        submenuLockBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const willBeLocked = !document.body.classList.contains('nav-lock');

            if (willBeLocked) {
                document.body.classList.add('nav-lock');
                document.body.classList.remove('nav-mouse-leave');
                leftNav.classList.remove('minimized');
                lockBtn.classList.add('active');
                submenuLockBtn.classList.add('active');
                lockBtn.setAttribute('aria-expanded', 'true');
                submenuLockBtn.setAttribute('aria-expanded', 'true');
                localStorage.setItem('nav-lock', 'true');
            } else {
                document.body.classList.remove('nav-lock');
                lockBtn.classList.remove('active');
                submenuLockBtn.classList.remove('active');
                lockBtn.setAttribute('aria-expanded', 'false');
                submenuLockBtn.setAttribute('aria-expanded', 'false');
                localStorage.setItem('nav-lock', 'false');
            }
        });
    }
});
