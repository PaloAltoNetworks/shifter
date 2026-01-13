/**
 * Sidebar Navigation Tests
 *
 * The sidebar.js module attaches event listeners on DOMContentLoaded.
 * We need to set up DOM before loading the module and then fire DOMContentLoaded.
 */

const buildSidebarMarkup = () => `
    <nav class="left-nav minimized" id="leftNav" data-active-submenu="">
        <button id="lockBtn" class="reset-button lock-button" aria-expanded="false"></button>
        <button class="nav-submenu-trigger" data-submenu="assets" data-submenu-title="Assets"></button>
        <button class="nav-submenu-trigger" data-submenu="settings" data-submenu-title="Settings"></button>
        <div id="navSubmenuPanel"></div>
        <span id="navSubmenuTitle"></span>
        <div id="navSubmenuItems"></div>
        <button id="navBackBtn"></button>
        <button id="submenuLockBtn" aria-expanded="false"></button>
    </nav>
    <template id="submenu-assets">
        <a href="/agents">Agents</a>
        <a href="/ngfw">NGFWs</a>
    </template>
    <template id="submenu-settings">
        <a href="/settings">Settings</a>
    </template>
`;

/**
 * Helper to set up DOM and load sidebar module fresh
 */
function setupAndLoadSidebar(options = {}) {
    // Reset module cache
    jest.resetModules();

    // Set up DOM
    document.body.innerHTML = buildSidebarMarkup();
    document.body.className = '';

    // Set localStorage before loading module
    if (options.locked) {
        localStorage.setItem('nav-lock', 'true');
    } else {
        localStorage.removeItem('nav-lock');
    }

    if (options.activeSubmenu) {
        document.getElementById('leftNav').dataset.activeSubmenu = options.activeSubmenu;
    }

    // Load module - it registers DOMContentLoaded listener
    require('./sidebar.js');

    // Fire DOMContentLoaded to trigger initialization
    document.dispatchEvent(new Event('DOMContentLoaded'));
}

describe('Sidebar Navigation', () => {
    let cleanupFn = null;

    beforeEach(() => {
        localStorage.clear();
        document.body.className = '';
        document.body.innerHTML = '';
    });

    afterEach(() => {
        // Reset document event listeners by replacing document
        jest.resetModules();
    });

    describe('Lock button', () => {
        test('clicking lock button adds nav-lock class to body', () => {
            setupAndLoadSidebar();

            const lockBtn = document.getElementById('lockBtn');
            lockBtn.click();

            expect(document.body.classList.contains('nav-lock')).toBe(true);
        });

        test('clicking lock button removes minimized class from nav', () => {
            setupAndLoadSidebar();

            const leftNav = document.getElementById('leftNav');
            const lockBtn = document.getElementById('lockBtn');
            lockBtn.click();

            expect(leftNav.classList.contains('minimized')).toBe(false);
        });

        test('clicking lock button sets aria-expanded to true', () => {
            setupAndLoadSidebar();

            const lockBtn = document.getElementById('lockBtn');
            lockBtn.click();

            expect(lockBtn.getAttribute('aria-expanded')).toBe('true');
        });

        test('clicking lock button twice toggles state', () => {
            setupAndLoadSidebar();

            const lockBtn = document.getElementById('lockBtn');
            lockBtn.click();
            lockBtn.click();

            expect(document.body.classList.contains('nav-lock')).toBe(false);
            expect(localStorage.getItem('nav-lock')).toBe('false');
        });
    });

    describe('Hover behavior', () => {
        test('mouseenter expands nav when not locked', () => {
            setupAndLoadSidebar();

            const leftNav = document.getElementById('leftNav');
            leftNav.dispatchEvent(new MouseEvent('mouseenter'));

            expect(leftNav.classList.contains('minimized')).toBe(false);
        });

        test('mouseleave collapses nav when not locked', () => {
            setupAndLoadSidebar();

            const leftNav = document.getElementById('leftNav');
            leftNav.dispatchEvent(new MouseEvent('mouseenter'));
            leftNav.dispatchEvent(new MouseEvent('mouseleave'));

            expect(leftNav.classList.contains('minimized')).toBe(true);
        });

    });

    describe('Submenu triggers', () => {
        test('clicking submenu trigger opens submenu panel', () => {
            setupAndLoadSidebar();

            const leftNav = document.getElementById('leftNav');
            const trigger = document.querySelector('[data-submenu="assets"]');
            trigger.click();

            expect(leftNav.classList.contains('submenu-open')).toBe(true);
        });

        test('clicking submenu trigger sets title', () => {
            setupAndLoadSidebar();

            const trigger = document.querySelector('[data-submenu="assets"]');
            trigger.click();

            expect(document.getElementById('navSubmenuTitle').textContent).toBe('Assets');
        });

        test('clicking submenu trigger populates items from template', () => {
            setupAndLoadSidebar();

            const trigger = document.querySelector('[data-submenu="assets"]');
            trigger.click();

            const items = document.getElementById('navSubmenuItems');
            expect(items.innerHTML).toContain('Agents');
            expect(items.innerHTML).toContain('NGFWs');
        });

        test('clicking back button closes submenu panel', () => {
            setupAndLoadSidebar();

            const leftNav = document.getElementById('leftNav');
            const trigger = document.querySelector('[data-submenu="assets"]');
            const backBtn = document.getElementById('navBackBtn');

            trigger.click();
            backBtn.click();

            expect(leftNav.classList.contains('submenu-open')).toBe(false);
        });
    });

    describe('Initial state from localStorage', () => {
        test('restores locked state from localStorage', () => {
            setupAndLoadSidebar({ locked: true });

            const leftNav = document.getElementById('leftNav');
            const lockBtn = document.getElementById('lockBtn');

            expect(document.body.classList.contains('nav-lock')).toBe(true);
            expect(leftNav.classList.contains('minimized')).toBe(false);
            expect(lockBtn.classList.contains('active')).toBe(true);
        });

        test('starts minimized when not locked', () => {
            setupAndLoadSidebar({ locked: false });

            expect(document.body.classList.contains('nav-mouse-leave')).toBe(true);
        });
    });

    describe('Submenu lock button', () => {
        test('submenu lock button syncs with main lock button', () => {
            setupAndLoadSidebar();

            const lockBtn = document.getElementById('lockBtn');
            const submenuLockBtn = document.getElementById('submenuLockBtn');

            submenuLockBtn.click();

            expect(lockBtn.classList.contains('active')).toBe(true);
            expect(submenuLockBtn.classList.contains('active')).toBe(true);
        });
    });

    describe('Active submenu on page load', () => {
        test('opens submenu when data-active-submenu is set and nav is expanded', () => {
            // Set locked so nav starts expanded
            setupAndLoadSidebar({ locked: true, activeSubmenu: 'assets' });

            const leftNav = document.getElementById('leftNav');
            expect(leftNav.classList.contains('submenu-open')).toBe(true);
        });
    });
});
