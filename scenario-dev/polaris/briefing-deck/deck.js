(() => {
  const slides = Array.from(document.querySelectorAll('.slide'));
  const hud = document.getElementById('hud');
  const slideCounter = document.getElementById('slide-counter');
  const slideTitle = document.getElementById('slide-title');
  const overview = document.getElementById('overview');
  const overviewGrid = overview.querySelector('.overview__grid');

  const missionLogIndex = slides.findIndex(s => s.id === 'mission-log');
  const hudHiddenOn = new Set(['slide--cold-open', 'slide--classification', 'slide--splash', 'slide--operation', 'slide--closing']);

  let current = 0;

  function pad(n) { return String(n).padStart(2, '0'); }

  function render() {
    slides.forEach((s, i) => s.classList.toggle('is-active', i === current));
    const total = slides.length;
    slideCounter.textContent = `${pad(current + 1)} / ${pad(total)}`;
    slideTitle.textContent = slides[current].dataset.title || '';
    const cls = slides[current].className;
    const hideHud = [...hudHiddenOn].some(h => cls.includes(h));
    hud.classList.toggle('is-hidden', hideHud);
    if (window.location.hash !== `#${current + 1}`) {
      history.replaceState(null, '', `#${current + 1}`);
    }
  }

  function goto(i) {
    current = Math.max(0, Math.min(slides.length - 1, i));
    render();
    closeOverview();
  }

  function next() { goto(current + 1); }
  function prev() { goto(current - 1); }

  function buildOverview() {
    overviewGrid.innerHTML = '';
    slides.forEach((s, i) => {
      const cell = document.createElement('div');
      cell.className = 'overview__cell';
      cell.dataset.index = i;
      cell.innerHTML = `
        <div class="overview__cell__n">${pad(i + 1)}</div>
        <div class="overview__cell__title">${s.dataset.title || ''}</div>
      `;
      cell.addEventListener('click', () => goto(i));
      overviewGrid.appendChild(cell);
    });
  }

  function openOverview() {
    buildOverview();
    overview.hidden = false;
    const cells = overviewGrid.querySelectorAll('.overview__cell');
    cells.forEach(c => c.classList.remove('is-focus'));
    if (cells[current]) cells[current].classList.add('is-focus');
  }

  function closeOverview() { overview.hidden = true; }

  function toggleOverview() {
    if (overview.hidden) openOverview(); else closeOverview();
  }

  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;

    if (!overview.hidden) {
      if (k === 'Escape') { closeOverview(); e.preventDefault(); return; }
      if (k === 'Enter') {
        const f = overviewGrid.querySelector('.is-focus');
        if (f) goto(parseInt(f.dataset.index, 10));
        e.preventDefault();
        return;
      }
      return;
    }

    switch (k) {
      case 'ArrowRight':
      case 'PageDown':
      case ' ':
        next(); e.preventDefault(); break;
      case 'ArrowLeft':
      case 'PageUp':
        prev(); e.preventDefault(); break;
      case 'Home':
        goto(0); e.preventDefault(); break;
      case 'End':
        goto(slides.length - 1); e.preventDefault(); break;
      case 'Escape':
        toggleOverview(); e.preventDefault(); break;
      case 'm':
      case 'M':
        if (missionLogIndex >= 0) goto(missionLogIndex);
        e.preventDefault(); break;
      case 'r':
      case 'R':
        goto(0); e.preventDefault(); break;
      case 'h':
      case 'H':
        hud.classList.toggle('is-hidden'); e.preventDefault(); break;
      case 'f':
      case 'F':
        if (!document.fullscreenElement) document.documentElement.requestFullscreen();
        else document.exitFullscreen();
        e.preventDefault(); break;
    }
  });

  window.addEventListener('wheel', (e) => {
    if (!overview.hidden) return;
    if (Math.abs(e.deltaY) < 40) return;
    if (e.deltaY > 0) next(); else prev();
  }, { passive: true });

  let touchStartX = null;
  window.addEventListener('touchstart', e => touchStartX = e.touches[0].clientX);
  window.addEventListener('touchend', e => {
    if (touchStartX == null) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(dx) > 60) { dx < 0 ? next() : prev(); }
    touchStartX = null;
  });

  const hash = parseInt((window.location.hash || '#1').slice(1), 10);
  if (!Number.isNaN(hash) && hash >= 1 && hash <= slides.length) current = hash - 1;
  render();

  let idleTimer;
  document.addEventListener('mousemove', () => {
    document.body.style.cursor = 'default';
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => document.body.style.cursor = 'none', 2500);
  });
})();
