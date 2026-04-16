// Operation NORTHSTORM — event analysis viewer

const COLORS = {
  amber:  '#ffb300',
  cyan:   '#4dd0ff',
  red:    '#ff3b30',
  green:  '#4cd964',
  dim:    '#8a929a',
  line:   '#1a2330',
  panel:  '#11151d',
};
const DIFF_COLOR = {
  easy:   COLORS.green,
  medium: COLORS.cyan,
  hard:   COLORS.amber,
  expert: COLORS.red,
};
const CLUSTER_COLOR = {
  'likely-agentic':       COLORS.cyan,
  'high-accuracy-slow':   COLORS.green,
  'burst-low-accuracy':   COLORS.amber,
  'mixed':                '#e6a443',
  'manual-struggling':    COLORS.red,
  'engaged-unsuccessful': '#a03a3a',
  'low-engagement':       COLORS.dim,
  'inactive':             '#3a3f48',
};

Chart.defaults.color = COLORS.dim;
Chart.defaults.borderColor = COLORS.line;
Chart.defaults.font.family = '"JetBrains Mono","SF Mono",Menlo,monospace';
Chart.defaults.font.size = 11;

function fmtPct(x)  { return (x == null) ? '—' : (x * 100).toFixed(0) + '%'; }
function fmtPct1(x) { return (x == null) ? '—' : (x * 100).toFixed(1) + '%'; }
function fmtNum(x)  { return (x == null) ? '—' : x.toLocaleString(); }

fetch('data/analysis.json')
  .then(r => r.json())
  .then(render)
  .catch(err => { document.body.innerHTML = '<pre style="padding:2rem;color:#ff3b30">Failed to load analysis.json: ' + err + '</pre>'; });

function render(d) {
  document.getElementById('generated-at').textContent = d.generated_at;

  renderSummary(d);
  renderHeadlines(d);
  renderDifficulty(d);
  renderMissions(d);
  renderCeiling(d);
  renderTimeline(d);
  renderArrival(d);
  renderPareto(d);
  renderUserTable(d);
  renderScoreHist(d);
  renderChallenges(d);
  renderClusters(d);
  renderRateLimits(d);
  renderHints(d);
  renderHintROI(d);
  renderGrind(d);
  renderTakeaways(d);
}

// --- summary ---

function renderSummary(d) {
  const s = d.summary;
  const rlPct = (s.ratelimited_total / s.submissions_total * 100).toFixed(0);
  const cards = [
    { label: 'Participants',   value: s.participants_total,  sub: `${s.participants_active} active · ${s.participants_scoring} scored` },
    { label: 'Challenges',     value: s.challenges_visible,  sub: 'visible on board' },
    { label: 'Solves',         value: fmtNum(s.solves_total),    sub: `of ${fmtNum(s.correct_total + s.incorrect_total)} real attempts` },
    { label: 'Rate-limited',   value: fmtNum(s.ratelimited_total),  sub: `${rlPct}% of all submissions` },
    { label: 'Hint unlocks',   value: s.hint_unlocks_total,  sub: 'across all participants' },
    { label: 'Top score',      value: fmtNum(s.top_score),   sub: `mean active ${fmtNum(s.mean_score_of_active)} · median ${fmtNum(s.median_score)}` },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div><div class="sub">${c.sub}</div></div>`
  ).join('');
}

// --- headlines (big takeaways up top) ---

function renderHeadlines(d) {
  const s = d.summary;
  const m5 = d.mission_funnel.M5 || {};
  const m3 = d.mission_funnel.M3 || {};
  const bigLifts = d.hint_impact.filter(h => h.lift >= 0.8).length;
  const ceilingCount = d.users.filter(u => u.points === d.users[0].points).length;
  const activePct = Math.round(s.participants_active / s.participants_total * 100);
  const wf = d.workflow_summary || {};
  const claudeDrives = wf['Claude drives submission'] || 0;
  const copyPaste = wf['human-in-loop (copy-paste from Claude)'] || 0;
  const discoveredMid = d.discovered_mid_event_count || 0;

  document.getElementById('headlines-body').innerHTML = `
    <h3>Submission-loop discoverability explains most of the score variance</h3>
    <p>Operators split into two dominant workflows: <strong>${copyPaste} copy-paste-from-Claude</strong> (reading Claude's output and typing the flag into CTFd) and <strong>${claudeDrives} Claude-drives-submission</strong> (Claude hits the flag endpoint directly). <strong>${discoveredMid} operators visibly transitioned mid-event</strong>, jumping from slow cadence to bursty — that's when they figured out Claude could submit. This discoverability gap, not AI quality or flag difficulty, is the biggest single source of score variance.</p>

    <h3>The ceiling is structural, not skill-based</h3>
    <p>${ceilingCount} operators tied at ${fmtNum(d.users[0].points)} points — all solved the <strong>exact same 49 challenges</strong>. Everything except M5 Bunker. Two of the four got there efficiently; two brute-forced it. Same result, dramatically different process cost.</p>

    <h3>Two bottlenecks in the main chain</h3>
    <p><strong>M3 Lab</strong>: ${m3.participants_attempted || 0} attempted, ${m3.participants_touched || 0} got any solve, ${m3.participants_completed || 0} cleared. Hard content once you're in — the pivot didn't auto-win the mission.
    <strong>M5 Bunker</strong>: ${m5.participants_attempted || 0} attempted, <strong>0 solved anything</strong>. Zero solves from 587 submissions. Either the splice→bunker path didn't fully open, or the OT protocol work is too far outside most operators' comfort zone for a 4-hour window.</p>

    <h3>Attendance, not difficulty, was the real gate</h3>
    <p>${s.participants_active}/${s.participants_total} enrolled accounts (${activePct}%) submitted anything. The onboarding funnel mattered more than the content tuning did.</p>

    <h3>The rate-limit story</h3>
    <p>${fmtNum(s.ratelimited_total)} rate-limit responses (${Math.round(s.ratelimited_total/s.submissions_total*100)}% of all HTTP submissions). Concentrated in the Claude-drives-submission cluster (~30% of their submissions throttled). CTFd's default limiter is tuned for human typing, not agentic loops — this is a platform-tuning lesson, not a participant-behavior problem.</p>

    <h3>Hints were load-bearing on hard content</h3>
    <p>${bigLifts} challenges had +80% or greater solve-rate lift for hint unlockers. By design (Hint 2 essentially gives the flag on hard content), but it means "pay for a hint" is economically "pay for the answer" at the top tiers.</p>
  `;
}

// --- difficulty ---

function renderDifficulty(d) {
  const labels = ['easy','medium','hard','expert'];
  const ds = d.difficulty_summary;
  const means = labels.map(l => ds[l] ? ds[l].mean_solve_rate * 100 : 0);
  new Chart(document.getElementById('chart-difficulty'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Mean solve rate %', data: means, backgroundColor: labels.map(l => DIFF_COLOR[l]) }] },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'Mean solve rate by designated difficulty', color: COLORS.cyan } },
      scales: { y: { beginAtZero: true, title: { display: true, text: '% of participants solved' } } },
    },
  });

  const t = document.getElementById('table-difficulty');
  t.innerHTML = `<thead><tr><th>Tier</th><th class="num">N</th><th class="num">Mean</th><th class="num">Median</th><th class="num">Min</th><th class="num">Max</th></tr></thead>`;
  const tb = document.createElement('tbody');
  labels.forEach(l => {
    const s = ds[l]; if (!s) return;
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td><span style="color:${DIFF_COLOR[l]}">${l}</span></td>` +
      `<td class="num">${s.count}</td>` +
      `<td class="num">${fmtPct1(s.mean_solve_rate)}</td>` +
      `<td class="num">${fmtPct1(s.median_solve_rate)}</td>` +
      `<td class="num">${fmtPct1(s.min_solve_rate)}</td>` +
      `<td class="num">${fmtPct1(s.max_solve_rate)}</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

// --- missions ---

function renderMissions(d) {
  const keys = Object.keys(d.mission_funnel).sort();
  const attempted = keys.map(k => d.mission_funnel[k].participants_attempted);
  const touched   = keys.map(k => d.mission_funnel[k].participants_touched);
  const cleared   = keys.map(k => d.mission_funnel[k].participants_completed);
  const challenges = keys.map(k => d.mission_funnel[k].challenges_in_mission);

  new Chart(document.getElementById('chart-missions'), {
    type: 'bar',
    data: {
      labels: keys.map((k,i) => `${k} (${challenges[i]}ch)`),
      datasets: [
        { label: 'Attempted',       data: attempted, backgroundColor: '#406280' },
        { label: 'Touched (≥1 solve)', data: touched,   backgroundColor: COLORS.cyan },
        { label: 'Fully cleared',    data: cleared,   backgroundColor: COLORS.amber },
      ],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: 'Mission funnel — attempted / touched / cleared', color: COLORS.cyan } },
      scales: { y: { beginAtZero: true, title: { display: true, text: 'participants' } } },
    },
  });
}

// --- ceiling ---

function renderCeiling(d) {
  const top = d.users.slice(0, 20);
  new Chart(document.getElementById('chart-top'), {
    type: 'bar',
    data: { labels: top.map(u => u.label), datasets: [{ data: top.map(u => u.points), backgroundColor: top.map((u,i) => i < d.users.filter(x => x.points === d.users[0].points).length ? COLORS.amber : '#7a5500') }] },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: { legend: { display: false }, title: { display: true, text: 'Top 20 scorers (amber = tied at ceiling)', color: COLORS.cyan } },
      scales: { x: { title: { display: true, text: 'points' } } },
    },
  });

  const ceilingUsers = d.users.filter(u => u.points === d.users[0].points);
  const el = document.getElementById('ceiling-facts');
  el.innerHTML = `
    <table>
      <thead><tr><th>Operator</th><th class="num">Solves</th><th class="num">Real attempts</th><th class="num">Success</th><th class="num">RL%</th><th class="num">Hints</th></tr></thead>
      <tbody>
        ${ceilingUsers.map(u => `
          <tr>
            <td>${u.label}</td>
            <td class="num">${u.solves}</td>
            <td class="num">${u.attempts_real}</td>
            <td class="num">${fmtPct(u.success_rate)}</td>
            <td class="num">${fmtPct(u.rate_limit_ratio)}</td>
            <td class="num">${u.hints_bought}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    <p style="margin-top:1rem;color:${COLORS.dim};font-size:0.9rem">Same score, same solve set, dramatically different <em>process</em>. Success rates range ${fmtPct(Math.min(...ceilingUsers.map(u=>u.success_rate)))} → ${fmtPct(Math.max(...ceilingUsers.map(u=>u.success_rate)))}. Two reached the ceiling efficiently; two brute-forced it with 3-6× the attempts.</p>
  `;
}

// --- timeline ---

function renderTimeline(d) {
  // Merge solve timeline + rate-limit timeline by minute
  const allMinutes = new Set([...d.timeline.map(p=>p.minute), ...d.rl_timeline.map(p=>p.minute)]);
  const minutes = [...allMinutes].sort((a,b)=>a-b);
  const solveMap = Object.fromEntries(d.timeline.map(p=>[p.minute,p]));
  const rlMap = Object.fromEntries(d.rl_timeline.map(p=>[p.minute,p]));
  const cum = [];
  let c = 0;
  minutes.forEach(m => { if (solveMap[m]) c = solveMap[m].cumulative; cum.push(c); });
  const rlPerMin = minutes.map(m => rlMap[m] ? rlMap[m].rate_limits : 0);

  new Chart(document.getElementById('chart-timeline'), {
    type: 'line',
    data: {
      labels: minutes.map(m => (m/60).toFixed(1)+'h'),
      datasets: [
        { label: 'Cumulative solves', data: cum, borderColor: COLORS.amber, backgroundColor: 'rgba(255,179,0,0.15)', fill: true, yAxisID: 'y1', tension: 0.2, pointRadius: 0 },
        { label: 'Rate-limit rejections / min', data: rlPerMin, borderColor: COLORS.red, backgroundColor: 'rgba(255,59,48,0.15)', yAxisID: 'y2', borderWidth: 1, pointRadius: 0 },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { title: { display: true, text: 'Solves and rate-limit rejections over time', color: COLORS.cyan } },
      scales: {
        x: { title: { display: true, text: 'hours after event start' }, ticks: { maxTicksLimit: 24 } },
        y1: { type: 'linear', position: 'left', title: { display: true, text: 'cumulative solves' } },
        y2: { type: 'linear', position: 'right', title: { display: true, text: 'rate-limits / min' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

// --- arrival ---

function renderArrival(d) {
  const bins = Object.keys(d.arrival_histogram).map(Number).sort((a,b)=>a-b);
  new Chart(document.getElementById('chart-arrival'), {
    type: 'bar',
    data: {
      labels: bins.map(b => `${b}–${b+15}`),
      datasets: [{ data: bins.map(b => d.arrival_histogram[b]), backgroundColor: COLORS.amber }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'First-submission offset from event start (minutes)', color: COLORS.cyan } },
      scales: { y: { beginAtZero: true, title: { display: true, text: 'participants' } } },
    },
  });
}

// --- pareto ---

function renderPareto(d) {
  const p = d.pareto;
  // Build a proper Lorenz curve: cumulative share of points as you add lower-ranked operators
  const active = d.users.filter(u => u.attempts_total > 0).sort((a,b) => b.points - a.points);
  const total = active.reduce((a,u) => a + u.points, 0);
  const xs = []; const ys_points = []; const ys_solves = [];
  const totalSolves = active.reduce((a,u) => a + u.solves, 0);
  let cp = 0, cs = 0;
  active.forEach((u, i) => {
    cp += u.points; cs += u.solves;
    xs.push(((i+1) / active.length * 100).toFixed(1));
    ys_points.push((cp / total * 100));
    ys_solves.push((cs / totalSolves * 100));
  });
  new Chart(document.getElementById('chart-pareto'), {
    type: 'line',
    data: {
      labels: xs,
      datasets: [
        { label: 'Points cumulative %', data: ys_points, borderColor: COLORS.amber, tension: 0.1, pointRadius: 0, fill: false },
        { label: 'Solves cumulative %', data: ys_solves, borderColor: COLORS.cyan,  tension: 0.1, pointRadius: 0, fill: false, borderDash: [4,4] },
      ],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: `Cumulative share of points (n=${active.length} active operators, ordered by rank)`, color: COLORS.cyan } },
      scales: {
        x: { title: { display: true, text: '% of operators (best → worst)' }, ticks: { maxTicksLimit: 10 } },
        y: { min: 0, max: 100, title: { display: true, text: '% captured' } },
      },
    },
  });
}

// --- full user table ---

function renderUserTable(d) {
  document.getElementById('user-count').textContent = d.users.length;
  const t = document.getElementById('table-users');
  t.innerHTML = `<thead><tr>
    <th>#</th><th>Label</th>
    <th class="num">Points</th><th class="num">Solves</th>
    <th class="num">Attempts</th><th class="num">Success</th>
    <th class="num">RL%</th><th class="num">Hints</th>
    <th class="num">Arrival</th><th class="num">Active min</th>
    <th>Cluster</th>
  </tr></thead>`;
  const tb = document.createElement('tbody');
  d.users.forEach((u,i) => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td class="num">${i+1}</td>` +
      `<td>${u.label}</td>` +
      `<td class="num">${fmtNum(u.points)}</td>` +
      `<td class="num">${u.solves}</td>` +
      `<td class="num">${u.attempts_real}</td>` +
      `<td class="num">${fmtPct(u.success_rate)}</td>` +
      `<td class="num">${fmtPct(u.rate_limit_ratio)}</td>` +
      `<td class="num">${u.hints_bought}</td>` +
      `<td class="num">${u.arrival_minutes!=null ? u.arrival_minutes.toFixed(0) : '—'}</td>` +
      `<td class="num">${u.active_minutes ?? '—'}</td>` +
      `<td><span class="cluster-pill ${u.cluster}">${u.cluster}</span></td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

// --- score histogram ---

function renderScoreHist(d) {
  const bins = Object.keys(d.score_histogram).sort((a,b)=>parseInt(a)-parseInt(b));
  new Chart(document.getElementById('chart-score-hist'), {
    type: 'bar',
    data: { labels: bins, datasets: [{ data: bins.map(b => d.score_histogram[b]), backgroundColor: COLORS.amber }] },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'Participants by score bin (includes 49 inactive at 0)', color: COLORS.cyan } },
      scales: { y: { beginAtZero: true, title: { display: true, text: 'participants' } } },
    },
  });
}

// --- challenges ---

function renderChallenges(d) {
  const sorted = [...d.challenges].sort((a,b) => b.solve_rate - a.solve_rate);
  new Chart(document.getElementById('chart-challenges'), {
    type: 'bar',
    data: {
      labels: sorted.map(c => c.name),
      datasets: [{ data: sorted.map(c => c.solve_rate * 100), backgroundColor: sorted.map(c => DIFF_COLOR[c.difficulty] || COLORS.dim), borderWidth: 0 }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: { display: true, text: 'Solve rate by challenge (colored by designated difficulty)', color: COLORS.cyan },
        tooltip: {
          callbacks: {
            afterBody: (ctx) => {
              const c = sorted[ctx[0].dataIndex];
              return [
                `mission: ${c.mission} · difficulty: ${c.difficulty} · value: ${c.value}`,
                `solves: ${c.solve_count} · attempter solve rate: ${fmtPct(c.conditional_solve_rate)}`,
                `real attempts: ${c.real_attempt_count} · rate-limited: ${c.rate_limited_count}`,
                `median attempts/solver: ${c.median_attempts_per_solver} · median min-to-solve: ${c.median_minutes_to_solve ?? '—'}`,
                `hint unlocks: ${c.hint_unlocks}`,
              ];
            },
          },
        },
      },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: '% participants solved' } },
        x: { ticks: { autoSkip: false, maxRotation: 80, minRotation: 50, font: { size: 9 } } },
      },
    },
  });
}

// --- clusters ---

function renderClusters(d) {
  new Chart(document.getElementById('chart-cluster-scatter'), {
    type: 'scatter',
    data: {
      datasets: Object.keys(CLUSTER_COLOR).map(cluster => ({
        label: cluster,
        data: d.users.filter(u => u.cluster === cluster).map(u => ({
          x: (u.success_rate || 0) * 100,
          y: u.burst_density * 100,
          user: u,
        })),
        backgroundColor: CLUSTER_COLOR[cluster],
        pointRadius: 5,
        pointHoverRadius: 8,
      })),
    },
    options: {
      responsive: true,
      plugins: {
        title: { display: true, text: 'Success rate vs burst density (per participant)', color: COLORS.cyan },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const u = ctx.raw.user;
              return `${u.label} — ${u.points} pts · ${u.solves} solves · ${u.attempts_real} real attempts`;
            },
          },
        },
      },
      scales: {
        x: { title: { display: true, text: 'success rate %' }, min: 0, max: 100 },
        y: { title: { display: true, text: 'burst density % (<2 s gaps)' }, min: 0, max: 100 },
      },
    },
  });

  const counts = d.cluster_summary;
  new Chart(document.getElementById('chart-cluster-bar'), {
    type: 'bar',
    data: { labels: Object.keys(counts), datasets: [{ data: Object.values(counts), backgroundColor: Object.keys(counts).map(k => CLUSTER_COLOR[k] || COLORS.dim) }] },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'Cluster membership', color: COLORS.cyan } },
      scales: { x: { beginAtZero: true, title: { display: true, text: 'participants' } } },
    },
  });
}

// --- rate limits ---

function renderRateLimits(d) {
  // timeline of RL per minute
  const rl = d.rl_timeline;
  new Chart(document.getElementById('chart-rl-timeline'), {
    type: 'bar',
    data: {
      labels: rl.map(p => (p.minute/60).toFixed(1)+'h'),
      datasets: [{ label: 'rate-limits / min', data: rl.map(p => p.rate_limits), backgroundColor: COLORS.red, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'Rate-limit responses per minute across the event', color: COLORS.cyan } },
      scales: { x: { title: { display: true, text: 'hours after event start' }, ticks: { maxTicksLimit: 24 } }, y: { beginAtZero: true } },
    },
  });

  const rs = d.rl_cluster_summary;
  const sorted = Object.entries(rs).sort((a,b) => b[1].mean_rl_ratio - a[1].mean_rl_ratio);
  new Chart(document.getElementById('chart-rl-cluster'), {
    type: 'bar',
    data: {
      labels: sorted.map(([k]) => k),
      datasets: [{
        label: 'Mean RL ratio %',
        data: sorted.map(([,v]) => v.mean_rl_ratio * 100),
        backgroundColor: sorted.map(([k]) => CLUSTER_COLOR[k] || COLORS.dim),
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      plugins: { legend: { display: false }, title: { display: true, text: 'Mean rate-limit ratio by cluster', color: COLORS.cyan } },
      scales: { x: { beginAtZero: true, title: { display: true, text: 'mean % of submissions rate-limited' } } },
    },
  });
}

// --- hint table ---

function renderHints(d) {
  const sorted = [...d.hint_impact].sort((a,b) => b.lift - a.lift);
  const t = document.getElementById('table-hints');
  t.innerHTML = `<thead><tr>
    <th>Challenge</th>
    <th class="num">Unlockers</th>
    <th class="num">Unlocker %</th>
    <th class="num">Non-unlocker %</th>
    <th class="num">Lift</th>
  </tr></thead>`;
  const tb = document.createElement('tbody');
  sorted.slice(0, 20).forEach(h => {
    const tr = document.createElement('tr');
    const liftColor = h.lift > 0.5 ? COLORS.amber : h.lift > 0 ? COLORS.green : COLORS.red;
    tr.innerHTML =
      `<td>${h.name}</td>` +
      `<td class="num">${h.unlockers}</td>` +
      `<td class="num">${fmtPct(h.unlocker_solve_rate)}</td>` +
      `<td class="num">${fmtPct(h.non_unlocker_solve_rate)}</td>` +
      `<td class="num" style="color:${liftColor}">${(h.lift>=0?'+':'')}${(h.lift*100).toFixed(0)}%</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

// --- hint ROI ---

function renderHintROI(d) {
  const r = d.hint_roi_summary;
  const el = document.getElementById('hint-roi-panel');
  el.innerHTML = `
    <div class="roi-grid">
      <div><div class="label">Users who bought hints</div><div class="big">${r.users_with_hints}</div></div>
      <div><div class="label">Net-positive</div><div class="big" style="color:${COLORS.green}">${r.users_net_positive}</div></div>
      <div><div class="label">Net-negative</div><div class="big" style="color:${COLORS.red}">${r.users_net_negative}</div></div>
      <div><div class="label">Wasted hints (unsolved)</div><div class="big">${r.wasted_hints}</div></div>
      <div><div class="label">Total spent</div><div class="big">${fmtNum(r.total_hint_spend)}</div></div>
      <div><div class="label">Earned on hinted</div><div class="big">${fmtNum(r.total_earned_on_hinted)}</div></div>
      <div><div class="label">Community net</div><div class="big" style="color:${r.net_community>0?COLORS.green:COLORS.red}">${r.net_community>0?'+':''}${fmtNum(r.net_community)}</div></div>
    </div>
    <p style="margin-top:1rem;color:${COLORS.dim};font-size:0.9rem">"Wasted hints" = unlocked but the operator never solved the challenge. That's spent points with no flag to show for it.</p>
  `;
}

// --- grind table ---

function renderGrind(d) {
  const t = document.getElementById('table-grind');
  t.innerHTML = `<thead><tr>
    <th>Challenge</th>
    <th>Mission</th>
    <th>Diff</th>
    <th class="num">Median attempts</th>
    <th class="num">Median min-to-solve</th>
    <th class="num">Solvers</th>
  </tr></thead>`;
  const tb = document.createElement('tbody');
  d.grind_challenges.forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>${c.name}</td>` +
      `<td>${c.mission}</td>` +
      `<td><span style="color:${DIFF_COLOR[c.difficulty]}">${c.difficulty}</span></td>` +
      `<td class="num">${c.median_attempts_per_solver}</td>` +
      `<td class="num">${c.median_minutes_to_solve ?? '—'}</td>` +
      `<td class="num">${c.solve_count}</td>`;
    tb.appendChild(tr);
  });
  t.appendChild(tb);
}

// --- takeaways ---

function renderTakeaways(d) {
  const s = d.summary;
  const m = d.mission_funnel;
  const ds = d.difficulty_summary;
  const rlc = d.rl_cluster_summary;

  // Find top cluster by RL pressure
  const rlSorted = Object.entries(rlc).sort((a,b) => b[1].mean_rl_ratio - a[1].mean_rl_ratio);

  const wf = d.workflow_summary || {};
  const dm = d.discovered_mid_event_count || 0;

  document.getElementById('takeaways-body').innerHTML = `
    <h3>The clusters are workflows, not Claude modes</h3>
    <p>The two "agentic-looking" clusters in §12 aren't two styles of AI — they're two different submission loops:</p>
    <ul style="color:var(--fg);margin:0 0 0.8rem 1.2rem">
      <li><strong>human-in-loop (copy-paste from Claude):</strong> ${wf['human-in-loop (copy-paste from Claude)'] || 0} operators. Claude does the investigation; the human types/pastes the flag into CTFd. Produces "high-accuracy-slow" telemetry — accuracy near 100% (Claude rarely proposes wrong flags) and paced in seconds-to-minutes (human copy-paste cadence).</li>
      <li><strong>Claude drives submission:</strong> ${wf['Claude drives submission'] || 0} operators. Operator gave Claude a path to submit flags directly. Produces "burst-low-accuracy" telemetry — fast bursts, lower per-submission accuracy because Claude also fires wrong guesses, much higher rate-limit ratio.</li>
    </ul>
    <p>Both are legitimate Claude-assisted play. The telemetry difference is the <em>submission loop configuration</em>, not the quality of the AI. That's the single biggest insight in this data.</p>

    <h3>Discoverability was the hidden variable</h3>
    <p><strong>${dm} operators visibly transitioned mid-event</strong> from copy-paste pacing to burst pacing — a bimodal burst-density signature where late-session bursts are ≥2× early-session bursts. That's the point where they figured out how to hand Claude the submission loop. Two of the four ceiling-tied operators (op024, op095) show this transition clearly.</p>
    <p>The implication: operator score variance was partly driven by <em>discovering</em> an advanced workflow partway through, not by raw skill or AI quality. This is a knowledge asymmetry we should directly address in the onboarding docs next time.</p>

    <h3>For content design</h3>
    <p><strong>Difficulty calibration held.</strong> Mean solve rates fell monotonically from easy (${fmtPct1(ds.easy.mean_solve_rate)}) → medium (${fmtPct1(ds.medium.mean_solve_rate)}) → hard (${fmtPct1(ds.hard.mean_solve_rate)}) → expert (${fmtPct1(ds.expert.mean_solve_rate)}). The designers' tiers matched observed difficulty.</p>
    <p><strong>M3 Lab was hard even once reached.</strong> Conditional solve rate (among the ${m.M3 ? m.M3.participants_attempted : 0} who attempted) was ${m.M3 ? Math.round(m.M3.participants_touched / (m.M3.participants_attempted || 1) * 100) : 0}%. The pivot didn't auto-win; the content needed real work.</p>
    <p><strong>M5 Bunker didn't open for anyone.</strong> 0 solves out of ${m.M5 ? m.M5.participants_attempted : 0} attempters. Either the blackout→splice chain failed to deliver the route for most, or the OT protocol work is too far outside comfort zones for a 4-hour window. Agentic tooling didn't substitute for either.</p>
    <p><strong>Hint 2 = the answer on hard content.</strong> ${d.hint_impact.filter(h => h.lift >= 0.8).length} challenges had +80% lift for hint unlockers. If the intent is "nudge not answer," Hint 2 on hard content needs rewriting.</p>

    <h3>For the platform</h3>
    <p><strong>CTFd's rate limiter threw ${fmtNum(s.ratelimited_total)} rejections</strong> (~26% of all submissions), concentrated in the Claude-drives-submission cluster (${fmtPct1(rlSorted[0][1].mean_rl_ratio)} mean throttle rate). An agentic-friendly rate-limit config — higher per-user caps, gentler penalties for wrong-flag bursts — would cut invisible friction. A sensible default for events where every participant has an AI co-operator.</p>
    <p><strong>Default CTFd behavior treated correct flags and wrong flags the same.</strong> That punishes the "Claude drives submission" workflow more than the "copy-paste from Claude" workflow. Worth revisiting.</p>

    <h3>For thinking about agentic CTF</h3>
    <p><strong>Attendance, not AI quality, is the real gate.</strong> ${s.participants_total - s.participants_active} of ${s.participants_total} enrolled operators (${Math.round((s.participants_total-s.participants_active)/s.participants_total*100)}%) never submitted. If AI co-operators were meant to lift the floor, that floor never met the carpet for half the room.</p>
    <p><strong>Pareto flattened.</strong> Top 10% captured ${fmtPct(d.pareto.top_10pct_points_share)} of points — less concentrated than classical CTF folklore. When everyone has Claude, the distribution flattens. For organizers: plan for fewer dramatic top-heavy outcomes; plan for richer mid-band engagement.</p>
    <p><strong>The ceiling was structural.</strong> 4 operators, same 49 flags, same wall at M5 Bunker. Agentic Claude doesn't brute-force structural gating — it amplifies operators who can already navigate the range, but it doesn't unlock content that requires external state the AI can't observe.</p>

    <h3>For next event</h3>
    <p><strong>Document the Claude-submits workflow up-front.</strong> Add an example to the AI-Assistant CTFd page. Don't leave it as hidden advanced knowledge — discoverability was a large source of variance.</p>
    <p><strong>Bake M5 Bunker accessibility.</strong> Either verify the splice mechanic reliably opens after M4, or put the bunker behind a less brittle gate. Right now it's technically reachable content that no operator reached.</p>
    <p><strong>Tune rate-limit config for agentic clients.</strong> Raise per-user throughput caps. Consider distinguishing "many wrong flags in a burst" (warn/backoff) from "many submissions overall" (allow).</p>
    <p><strong>Invest in the onboarding funnel.</strong> Half the enrolled operators never submitted. A 15-min warm-up that proves their environment works end-to-end (and surfaces the Claude-submits pattern as an option) would move that number.</p>
  `;
}
