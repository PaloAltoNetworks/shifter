/**
 * Cortex XDR Left Navigation - Direct port behavior
 */

// SonarCloud S1192: extracted duplicated string literals.
const NAV_LOCK_CLASS = 'nav-lock';
const NAV_MOUSE_LEAVE_CLASS = 'nav-mouse-leave';
const ARIA_EXPANDED_ATTR = 'aria-expanded';
const SUBMENU_OPEN_CLASS = 'is-open';

// Helper to open a submenu by ID
function openSubmenu(submenuId, els, state) {
    const trigger = document.querySelector(`.nav-submenu-trigger[data-submenu="${submenuId}"]`);
    const template = document.getElementById('submenu-' + submenuId);

    if (trigger && template && els.submenuPanel) {
        // Set the title
        if (els.submenuTitle) {
            els.submenuTitle.textContent = trigger.dataset.submenuTitle;
        }

        // Clear and populate submenu items
        if (els.submenuItems) {
            els.submenuItems.innerHTML = '';
            els.submenuItems.appendChild(template.content.cloneNode(true));
        }

        // Mark this trigger as active/open
        els.submenuTriggers.forEach(t => t.classList.remove(SUBMENU_OPEN_CLASS));
        trigger.classList.add(SUBMENU_OPEN_CLASS);

        // Open the submenu panel
        els.leftNav.classList.add('submenu-open');
        state.activeSubmenuId = submenuId;
    }
}

// Helper to close submenu panel (visual only, keeps activeSubmenuId if on submenu page)
function closeSubmenuPanel(els) {
    els.leftNav.classList.remove('submenu-open');
    els.submenuTriggers.forEach(t => t.classList.remove(SUBMENU_OPEN_CLASS));
}

// Expand on hover / collapse on mouse leave (both no-ops while locked)
function setupHoverBehavior(els, state) {
    els.leftNav.addEventListener('mouseenter', function() {
        document.body.classList.remove(NAV_MOUSE_LEAVE_CLASS);
        if (!document.body.classList.contains(NAV_LOCK_CLASS)) {
            els.leftNav.classList.remove('minimized');
            // Re-open submenu if we have an active one
            if (state.activeSubmenuId) {
                openSubmenu(state.activeSubmenuId, els, state);
            }
        }
    });

    els.leftNav.addEventListener('mouseleave', function() {
        document.body.classList.add(NAV_MOUSE_LEAVE_CLASS);
        if (!document.body.classList.contains(NAV_LOCK_CLASS)) {
            els.leftNav.classList.add('minimized');
            closeSubmenuPanel(els);
        }
    });
}

// Main lock button pins/unpins the expanded nav.
function setupLockButton(els, state) {
    els.lockBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();

        const willBeLocked = !document.body.classList.contains(NAV_LOCK_CLASS);

        if (willBeLocked) {
            document.body.classList.add(NAV_LOCK_CLASS);
            document.body.classList.remove(NAV_MOUSE_LEAVE_CLASS);
            els.leftNav.classList.remove('minimized');
            els.lockBtn.classList.add('active');
            els.lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
            localStorage.setItem(NAV_LOCK_CLASS, 'true');
            // Re-open submenu if we have an active one
            if (state.activeSubmenuId) {
                openSubmenu(state.activeSubmenuId, els, state);
            }
        } else {
            document.body.classList.remove(NAV_LOCK_CLASS);
            els.lockBtn.classList.remove('active');
            els.lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
            localStorage.setItem(NAV_LOCK_CLASS, 'false');
        }
    });
}

// Open submenu panel when clicking a submenu trigger.
function setupSubmenuTriggers(els, state) {
    els.submenuTriggers.forEach(trigger => {
        trigger.addEventListener('click', function(e) {
            e.preventDefault();
            const submenuId = this.dataset.submenu;
            openSubmenu(submenuId, els, state);
        });
    });
}

// Close submenu panel when clicking the back button.
function setupBackButton(els, state) {
    if (!els.backBtn) return;
    els.backBtn.addEventListener('click', function(e) {
        e.preventDefault();
        closeSubmenuPanel(els);
        // Only clear activeSubmenuId if we're not on a submenu page
        if (!els.leftNav.dataset.activeSubmenu) {
            state.activeSubmenuId = null;
        }
    });
}

// Submenu lock button - same behavior as main lock button
function setupSubmenuLockButton(els, isLocked) {
    const submenuLockBtn = document.getElementById('submenuLockBtn');
    if (!submenuLockBtn) return;

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
            document.body.classList.remove(NAV_MOUSE_LEAVE_CLASS);
            els.leftNav.classList.remove('minimized');
            els.lockBtn.classList.add('active');
            submenuLockBtn.classList.add('active');
            els.lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
            submenuLockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
            localStorage.setItem(NAV_LOCK_CLASS, 'true');
        } else {
            document.body.classList.remove(NAV_LOCK_CLASS);
            els.lockBtn.classList.remove('active');
            submenuLockBtn.classList.remove('active');
            els.lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
            submenuLockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'false');
            localStorage.setItem(NAV_LOCK_CLASS, 'false');
        }
    });
}

// User menu dropdown open/close behavior.
function setupUserMenu() {
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userMenuContainer = userMenuBtn?.closest('.nav-profile-container');

    if (!userMenuBtn || !userMenuContainer) return;

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

document.addEventListener('DOMContentLoaded', function() {
    const leftNav = document.getElementById('leftNav');
    const lockBtn = document.getElementById('lockBtn');

    if (!leftNav || !lockBtn) return;

    // Bundle the nav DOM elements shared by the setup helpers.
    const els = {
        leftNav,
        lockBtn,
        submenuPanel: document.getElementById('navSubmenuPanel'),
        submenuTitle: document.getElementById('navSubmenuTitle'),
        submenuItems: document.getElementById('navSubmenuItems'),
        backBtn: document.getElementById('navBackBtn'),
        submenuTriggers: document.querySelectorAll('.nav-submenu-trigger'),
    };

    // Track which submenu is currently active (persists across minimize/expand)
    const state = { activeSubmenuId: leftNav.dataset.activeSubmenu || null };

    // Check localStorage for lock state
    const isLocked = localStorage.getItem(NAV_LOCK_CLASS) === 'true';

    if (isLocked) {
        document.body.classList.add(NAV_LOCK_CLASS);
        leftNav.classList.remove('minimized');
        lockBtn.classList.add('active');
        lockBtn.setAttribute(ARIA_EXPANDED_ATTR, 'true');
    }

    // Auto-open submenu if we're on a submenu page
    if (state.activeSubmenuId && !leftNav.classList.contains('minimized')) {
        openSubmenu(state.activeSubmenuId, els, state);
    }

    setupHoverBehavior(els, state);
    setupLockButton(els, state);

    // Initial state - start with mouse leave (unless locked)
    if (!isLocked) {
        document.body.classList.add(NAV_MOUSE_LEAVE_CLASS);
    }

    setupSubmenuTriggers(els, state);
    setupBackButton(els, state);
    setupSubmenuLockButton(els, isLocked);
    setupUserMenu();
});
