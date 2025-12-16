/**
 * Cortex XDR Left Navigation - Direct port behavior
 */

document.addEventListener('DOMContentLoaded', function() {
    const leftNav = document.getElementById('leftNav');
    const lockBtn = document.getElementById('lockBtn');

    if (!leftNav || !lockBtn) return;

    // Check localStorage for lock state
    const isLocked = localStorage.getItem('nav-lock') === 'true';

    if (isLocked) {
        document.body.classList.add('nav-lock');
        leftNav.classList.remove('minimized');
        lockBtn.classList.add('active');
        lockBtn.setAttribute('aria-expanded', 'true');
    }

    // Expand on hover (if not locked)
    leftNav.addEventListener('mouseenter', function() {
        document.body.classList.remove('nav-mouse-leave');
        if (!document.body.classList.contains('nav-lock')) {
            leftNav.classList.remove('minimized');
        }
    });

    // Collapse on mouse leave (if not locked)
    leftNav.addEventListener('mouseleave', function() {
        document.body.classList.add('nav-mouse-leave');
        if (!document.body.classList.contains('nav-lock')) {
            leftNav.classList.add('minimized');
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
        } else {
            document.body.classList.remove('nav-lock');
            // Don't minimize or hide immediately - let mouseleave handle it
            lockBtn.classList.remove('active');
            lockBtn.setAttribute('aria-expanded', 'false');
            localStorage.setItem('nav-lock', 'false');
        }
    });

    // Initial state - start with mouse leave
    document.body.classList.add('nav-mouse-leave');
});
