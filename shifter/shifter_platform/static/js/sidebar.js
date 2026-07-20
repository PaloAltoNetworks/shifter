/**
 * Cortex XDR Left Navigation - Direct port behavior
 */

// SonarCloud S1192: extracted duplicated string literals.
const NAV_LOCK_CLASS = 'nav-lock';
const ARIA_EXPANDED_ATTR = 'aria-expanded';
const SUBMENU_OPEN_CLASS = 'is-open';

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
                submenuTitle.textContent = trigger.dataset.submenuTitle;
            }

            // Clear and populate submenu items
            if (submenuItems) {
                submenuItems.innerHTML = '';
                submenuItems.appendChild(template.content.cloneNode(true));
            }

            // Mark this trigger as active/open
            submenuTriggers.forEach(t => t.classList.remove(SUBMENU_OPEN_CLASS));
            trigger.classList.add(SUBMENU_OPEN_CLASS);

            // Open the submenu panel
            leftNav.classList.add('submenu-open');
            activeSubmenuId = submenuId;
        }
    }

    // Helper to close submenu panel (visual only, keeps activeSubmenuId if on submenu page)
    function closeSubmenuPanel() {
        leftNav.classList.remove('submenu-open');
        submenuTriggers.forEach(t => t.classList.remove(SUBMENU_OPEN_CLASS));
    }

    // Check localStorage for lock state
    const isLocked = localStorage.getItem(NAV_LOCK_CLASS) === 'true';

    if (isLocked) {
        document.body.classList.add(NAV_LOCK_CLASS);
        leftNav.classList.remove('minimized');
        lockBtn.classList.add('active');
        lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
    }

    // Auto-open submenu if we're on a submenu page
    if (activeSubmenuId && !leftNav.classList.contains('minimized')) {
        openSubmenu(activeSubmenuId);
    }

    // Expand on hover (if not locked)
    leftNav.addEventListener('mouseenter', function() {
        document.body.classList.remove('nav-mouse-leave');
        if (!document.body.classList.contains(NAV_LOCK_CLASS)) {
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
        if (!document.body.classList.contains(NAV_LOCK_CLASS)) {
            leftNav.classList.add('minimized');
            closeSubmenuPanel();
        }
    });

    // Lock button click
    lockBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();

        const willBeLocked = !document.body.classList.contains(NAV_LOCK_CLASS);

        if (willBeLocked) {
            document.body.classList.add(NAV_LOCK_CLASS);
            document.body.classList.remove('nav-mouse-leave');
            leftNav.classList.remove('minimized');
            lockBtn.classList.add('active');
            lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
            localStorage.setItem(NAV_LOCK_CLASS, 'true');
            // Re-open submenu if we have an active one
            if (activeSubmenuId) {
                openSubmenu(activeSubmenuId);
            }
        } else {
            document.body.classList.remove(NAV_LOCK_CLASS);
            lockBtn.classList.remove('active');
            lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
            localStorage.setItem(NAV_LOCK_CLASS, 'false');
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
            const submenuId = this.dataset.submenu;
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
            submenuLockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
        }

        submenuLockBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const willBeLocked = !document.body.classList.contains(NAV_LOCK_CLASS);

            if (willBeLocked) {
                document.body.classList.add(NAV_LOCK_CLASS);
                document.body.classList.remove('nav-mouse-leave');
                leftNav.classList.remove('minimized');
                lockBtn.classList.add('active');
                submenuLockBtn.classList.add('active');
                lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
                submenuLockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
                localStorage.setItem(NAV_LOCK_CLASS, 'true');
            } else {
                document.body.classList.remove(NAV_LOCK_CLASS);
                lockBtn.classList.remove('active');
                submenuLockBtn.classList.remove('active');
                lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
                submenuLockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
                localStorage.setItem(NAV_LOCK_CLASS, 'false');
            }
        });
    }

    // User menu dropdown
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userMenuContainer = userMenuBtn?.closest('.nav-profile-container');

    if (userMenuBtn && userMenuContainer) {
        // Toggle menu on click
        userMenuBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            const isOpen = userMenuContainer.classList.contains('open');
            userMenuContainer.classList.toggle('open');
            userMenuBtn.setAttribute(ARIA_EXPANDED_ATTR, !isOpen);
        });

        // Close menu when clicking outside
        document.addEventListener('click', function(e) {
            if (!userMenuContainer.contains(e.target)) {
                userMenuContainer.classList.remove('open');
                userMenuBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
            }
        });

        // Close menu on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && userMenuContainer.classList.contains('open')) {
                userMenuContainer.classList.remove('open');
                userMenuBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
                userMenuBtn.focus();
            }
        });
    }
});
