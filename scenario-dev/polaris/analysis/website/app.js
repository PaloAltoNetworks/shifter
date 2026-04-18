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
  renderLandscape(d);
  renderStuck(d);
  renderTakeaways(d);
}

function renderLandscape(d) {
  const el = document.getElementById('landscape-body');
  el.innerHTML = `
    <h3>How common is "every participant has their own AI agent in an isolated range"?</h3>
    <p>Effectively unprecedented at 100+ participants with a frontier agent per operator. Related formats:</p>
    <ul>
      <li><strong>AI-vs-human CTFs</strong> — autonomous agent teams competing <em>against</em> humans. Example: <a href="https://www.hackthebox.com/blog/ai-vs-human-ctf-hack-the-box-results">HTB × Palisade Research (Jan 2025)</a>: 8 agent teams vs 153 human teams on 20 crypto/reverse challenges. Different format from ours.</li>
      <li><strong>AI-as-copilot pilots</strong> — HTB's <a href="https://www.hackthebox.com/blog/attack-of-the-agents-ctf">"Attack of the Agents" (June 2025)</a> tested AI copilots for small groups via their MCP integration. Similar format, much smaller scale.</li>
      <li><strong>Agent-building competitions</strong> — <a href="https://www.csaw.io/agentic-automated-ctf">CSAW Agentic Automated CTF (2025)</a>: participants <em>build</em> the agent rather than play with it.</li>
      <li><strong>BYO-AI</strong> — widely tolerated at BSides / picoCTF / etc., but no uniform provisioning, no controlled environment. Measurement not comparable.</li>
    </ul>
    <p>Polaris-format (uniform preconfigured frontier agent, 110 isolated ranges, IT+OT content, difficulty-calibrated challenge set) doesn't have a published analog I could find.</p>

    <h3>What's published on AI impact on CTF solve rates?</h3>
    <ul>
      <li><strong>DARPA AIxCC final</strong> (DEF CON 33, Aug 2025) — autonomous cyber reasoning systems found 86% of synthetic vulns, 18 real 0-days. Measures agent capability, not human-plus-agent. <a href="https://www.darpa.mil/news/2025/aixcc-results">results</a></li>
      <li><strong>Cybench</strong> (Stanford CRFM, NeurIPS 2024, <a href="https://arxiv.org/abs/2408.08926">arXiv:2408.08926</a>) — agent first-solve-time correlates with human difficulty; strong cliff above ~11 minutes. Closest published analog to our difficulty-gradient result.</li>
      <li><strong>NYU CTF Bench</strong> (NeurIPS 2024, <a href="https://arxiv.org/abs/2406.05590">arXiv:2406.05590</a>), <strong>EnIGMA</strong>, <strong>CTF-Dojo</strong>, <strong>CAI</strong>. All agent-capability evals.</li>
      <li><strong>UK AISI Claude "Mythos Preview" eval</strong> (Apr 2026): 73% on expert cyber tasks; Claude at top 3% on PicoCTF 2025. <a href="https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities">report</a></li>
      <li><strong>Suzu Labs / Security Boulevard — "Death of the CTF"</strong> (Mar 2026): root-blood times on HTB declining ~16%/yr post-LLM, with 27% (Hard) → 67% (Insane) compression across difficulty tiers.</li>
    </ul>

    <h3>Is our "monotonic solve-rate decline despite AI access" result novel?</h3>
    <p><strong>Direction:</strong> expected. Cybench and Suzu Labs both show agents still hit a difficulty ceiling.</p>
    <p><strong>What's plausibly new in this data:</strong></p>
    <ul>
      <li>The pattern holding at <strong>scale in a human population</strong> (61 active operators, each with an agent) rather than in agent-only benchmarks or single-operator pilots.</li>
      <li>Clean calibration (33% / 21% / 8% / 3% easy→expert) surviving universal AI access — a stronger claim than "agents have a ceiling"; this is "the <em>designers' labels</em> still sorted the content correctly when every participant had AI help."</li>
      <li>The <strong>IT+OT mix</strong> — specifically SCADA/Modbus and a custom binary protocol. OT content is near-absent from published LLM-CTF literature.</li>
    </ul>

    <h3>Honest gaps</h3>
    <ul>
      <li>We can't rule out unpublished industry events running similar formats. "Unprecedented" is "I couldn't find one published."</li>
      <li>Our inference about <em>why</em> solve rates fell (ie what specifically made expert harder than hard for AI-assisted teams) isn't in the data — we see the what, not the why. Causal claims would need a controlled comparison.</li>
      <li>The M5 Bunker confound — the hardest mission was also the broken one. The solve rate on M5 says nothing about its actual difficulty.</li>
    </ul>

    <p class="small" style="margin-top:1rem;color:var(--fg-dim)">Research compiled April 2026. See citations for original sources.</p>
  `;
}

function renderStuck(d) {
  const fo = (d.stuck_signatures || {}).full_override || [];
  const frustration = d.frustration_index || [];

  const tS = document.getElementById('table-stuck');
  tS.innerHTML = `<thead><tr>
    <th>Operator</th><th>Category</th>
    <th class="num">Total subs</th>
    <th class="num">Exact code</th>
    <th class="num">3-piece variants</th>
    <th class="num">2-piece variants</th>
    <th class="num">FLAG{} guesses</th>
    <th>Solved?</th>
  </tr></thead>`;
  const tb = document.createElement('tbody');
  fo.forEach(r => {
    const color = r.category === 'HAS_ANSWER_STUCK' ? COLORS.red :
                  r.category === 'KNOWS_PIECES_STUCK' ? COLORS.amber :
                  r.category === 'BRUTE_SPRAYING' ? COLORS.amber :
                  r.category === 'SOLVED' ? COLORS.green : COLORS.dim;
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>op${String(r.op_num).padStart(3,'0')}</td>` +
      `<td style="color:${color};font-weight:600">${r.category}</td>` +
      `<td class="num">${r.total_subs}</td>` +
      `<td class="num">${r.exact_correct_code_submitted}</td>` +
      `<td class="num">${r.three_piece_variants}</td>` +
      `<td class="num">${r.two_piece_variants}</td>` +
      `<td class="num">${r.flag_format_guesses}</td>` +
      `<td>${r.solved ? '<span style="color:'+COLORS.green+'">yes</span>' : 'no'}</td>`;
    tb.appendChild(tr);
  });
  tS.appendChild(tb);

  const tF = document.getElementById('table-frustration');
  tF.innerHTML = `<thead><tr>
    <th>Operator</th><th>Mission</th>
    <th class="num">Submissions</th>
    <th class="num">Solves</th>
  </tr></thead>`;
  const tfb = document.createElement('tbody');
  frustration.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>op${String(r.op_num).padStart(3,'0')}</td>` +
      `<td>${r.mission}</td>` +
      `<td class="num" style="color:${r.submissions > 100 ? COLORS.red : COLORS.amber}">${r.submissions}</td>` +
      `<td class="num">${r.solves}</td>`;
    tfb.appendChild(tr);
  });
  tF.appendChild(tfb);
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
  const ds = d.difficulty_summary;
  const bigLifts = d.hint_impact.filter(h => h.lift >= 0.8).length;
  const ceilingCount = d.users.filter(u => u.points === d.users[0].points).length;
  const wf = d.workflow_summary || {};
  const claudeDrives = wf['Claude drives submission'] || 0;
  const copyPaste = wf['human-in-loop (copy-paste from Claude)'] || 0;
  const discoveredMid = d.discovered_mid_event_count || 0;
  const fo = (d.stuck_signatures || {}).full_override || [];
  const hasAnswerStuck = fo.filter(r => r.category === 'HAS_ANSWER_STUCK').length;
  const knowsPiecesStuck = fo.filter(r => r.category === 'KNOWS_PIECES_STUCK').length;

  document.getElementById('headlines-body').innerHTML = `
    <div class="confidence-note"><strong>Note on confidence:</strong> the findings below are graded — <span style="color:${COLORS.green}">STRONG</span> means the signal maps cleanly to a known mechanic (specific flag values, baked infrastructure, etc.); <span style="color:${COLORS.amber}">SUGGESTIVE</span> means the data is consistent with an interpretation but multiple alternatives fit; <span style="color:${COLORS.dim}">DESCRIPTIVE</span> means we're reporting aggregates without claiming causation.</div>

    <h3>Difficulty calibration held under universal AI access <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG</span></h3>
    <p>Every participant had a frontier Claude agent (Sonnet 4.5 / 4.6) preconfigured. Despite that, solve rates fell monotonically across designated difficulty tiers: easy ${fmtPct1(ds.easy.mean_solve_rate)} → medium ${fmtPct1(ds.medium.mean_solve_rate)} → hard ${fmtPct1(ds.hard.mean_solve_rate)} → expert ${fmtPct1(ds.expert.mean_solve_rate)}. The designers' difficulty labels matched observed behavior. <strong>This is the headline result</strong> — it means the challenge set remained meaningful and differentiated even with AI assistance, which was not a given. (Related result in <a href="https://arxiv.org/abs/2408.08926">Cybench</a>: agents showed a clean first-solve-time cliff that correlated with human difficulty; we observe the same gradient survives in a 61-operator human population running with agents.)</p>

    <h3>M5 Bunker was an infrastructure failure, not a content failure <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG</span></h3>
    <p>0 of ${m5.participants_attempted || 0} Bunker attempters solved anything. <strong>${hasAnswerStuck} operators submitted the correct override code <code>7741-MN07-AL42</code> directly to CTFd</strong>, having assembled it from three separate range artifacts. They were stuck at the transport layer: a splice-watcher bug (looking for container <code>a5-scada-generator</code> instead of <code>a5-scada</code>) prevented <code>a14-kali</code> from ever attaching to the bunker network, so the <code>override</code> command could never be sent to the brain. Those operators had the answer; they had nowhere to send it. This reading is tightly constrained by the data — exact-string match on a known code is an unambiguous signal.</p>

    <h3>The ceiling is structural <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG</span></h3>
    <p>${ceilingCount} operators tied at ${fmtNum(d.users[0].points)} points — all solved the <strong>exact same 49 challenges</strong> (everything except M5 Bunker). Same wall, same cause: the splice-watcher bug.</p>

    <h3>Stuck-signature detection as an infra-health canary <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG for Bunker, weaker elsewhere</span></h3>
    <p>For the Bunker case, the canary is clean: we know what the exact correct code is, so exact-match detection against non-solving submissions is definitive. For other challenges without a single known "near-answer" string, the signal degrades. The method is cheap to implement ahead of the next event and worth it <em>for challenges where we can pre-declare what "close but missing" looks like</em>.</p>

    <h3>Workflow splits in submission cadence <span class="badge" style="background:rgba(255,179,0,0.2);color:${COLORS.amber}">SUGGESTIVE</span></h3>
    <p>Operators split into clusters based on success rate and inter-submission gap: <strong>${copyPaste} high-accuracy-slow</strong>, <strong>${claudeDrives} burst-low-accuracy</strong>, and <strong>${discoveredMid} who visibly shifted from slow to bursty mid-event</strong>. The intuition is that these correspond to "Claude writes, human copy-pastes" vs. "Claude drives submissions," with some operators discovering the latter partway through. <strong>Caveat:</strong> submission cadence alone doesn't distinguish agentic-spraying from human-fatigue-guessing or misconfigured-agent-loops. Treat this as a plausible hypothesis, not a proven decomposition.</p>

    <h3>M3 Lab was genuine difficulty <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG</span></h3>
    <p>${m3.participants_attempted || 0} attempted, ${m3.participants_touched || 0} got any solve, ${m3.participants_completed || 0} cleared. Unlike M5, the mission gradient is clean and the content was reachable. Runs-out-of-time-and-technique, not infrastructure failure.</p>

    <h3>Rate-limit volume <span class="badge" style="background:rgba(138,146,154,0.2);color:${COLORS.dim}">DESCRIPTIVE</span></h3>
    <p>${fmtNum(s.ratelimited_total)} rate-limit responses (${Math.round(s.ratelimited_total/s.submissions_total*100)}% of all HTTP submissions). Concentrated in the high-burst cohort. We can't cleanly attribute "why" — bruteforcing flags, agentic loops hitting the endpoint, frustrated retrying, misconfigured scripts — all produce the same telemetry. What's defensible: CTFd's default rate-limit config is tuned for human typing cadence, and events with AI agents should raise per-user caps.</p>

    <h3>Hints were load-bearing on hard content <span class="badge" style="background:rgba(76,217,100,0.2);color:${COLORS.green}">STRONG</span></h3>
    <p>${bigLifts} challenges had +80% or greater solve-rate lift for hint unlockers. By design (Hint 2 essentially gives the flag on hard content), but it means "pay for a hint" is economically "pay for the answer" at the top tiers. If the intent is "nudge not answer," Hint 2 on hard challenges needs rewriting.</p>
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
  const fo = (d.stuck_signatures || {}).full_override || [];
  const hasAnswerStuck = fo.filter(r => r.category === 'HAS_ANSWER_STUCK');

  document.getElementById('takeaways-body').innerHTML = `
    <h3>The single most important finding</h3>
    <p><strong>M5 Bunker's zero-solve rate was caused by a deployment bug, not by design or skill.</strong> The splice-watcher systemd unit on every polaris-vm was configured with a container name (<code>a5-scada-generator</code>) that didn't match what was actually baked (<code>a5-scada</code>). The watcher silently failed every 10 seconds for ~30 hours. Every operator who tripped the A5 meltdown (by solving Lights Out) SHOULD have had <code>a14-kali</code> attached to <code>build_splice-link</code> automatically — none did. The bunker was unreachable for the entire event window.</p>
    <p>This is a deployment issue, not a content issue. Once patched mid-event (env var override <code>A5_CONTAINER=a5-scada</code>), the splice worked correctly for any fresh meltdown. Twelve of the operators who had done the M4 work got a manual splice and were given the 24h extension to finish.</p>

    <h3>Stuck-signature detection could have caught this live</h3>
    <p>The signature was visible in the data throughout the event: operators submitting <strong>the correct override code directly to CTFd</strong> instead of ever claiming the resulting flag. ${hasAnswerStuck.length} operators did this — they had everything they needed to win except the network route to execute the final mechanic:</p>
    <ul style="color:var(--fg);margin:0 0 0.8rem 1.2rem">
      ${hasAnswerStuck.map(r => `<li><strong>op${r.op_num}</strong> — submitted correct code <code>7741-MN07-AL42</code> ${r.exact_correct_code_submitted}× (plus ${r.three_piece_variants} permutation variants and ${r.flag_format_guesses} FLAG{hex} guesses, zero solves on Full Override).</li>`).join('')}
    </ul>
    <p><strong>Build this into the dashboard for next event.</strong> A cheap rule: for each challenge, count submissions matching a pre-declared "near-answer" regex. When ≥2 operators are ≥5 submissions deep in near-answers without a single solve, page the operations team. The data to detect infrastructure failures is in the scoreboard itself — we just weren't watching for this pattern.</p>

    <h3>The clusters are workflows, not Claude modes</h3>
    <p>The two "agentic-looking" clusters in §12 aren't two styles of AI — they're two different submission loops:</p>
    <ul style="color:var(--fg);margin:0 0 0.8rem 1.2rem">
      <li><strong>human-in-loop (copy-paste from Claude):</strong> ${wf['human-in-loop (copy-paste from Claude)'] || 0} operators. Claude does the investigation; the human types/pastes the flag into CTFd. Produces "high-accuracy-slow" telemetry — accuracy near 100% (Claude rarely proposes wrong flags) and paced in seconds-to-minutes (human copy-paste cadence).</li>
      <li><strong>Claude drives submission:</strong> ${wf['Claude drives submission'] || 0} operators. Operator gave Claude a path to submit flags directly. Produces "burst-low-accuracy" telemetry — fast bursts, lower per-submission accuracy because Claude also fires wrong guesses, much higher rate-limit ratio.</li>
    </ul>
    <p>Both are legitimate Claude-assisted play. The telemetry difference is the <em>submission loop configuration</em>, not the quality of the AI.</p>

    <h3>Discoverability was the hidden score-variance driver</h3>
    <p><strong>${dm} operators visibly transitioned mid-event</strong> from copy-paste pacing to burst pacing — a bimodal burst-density signature where late-session bursts are ≥2× early-session bursts. That's the point where they figured out Claude could submit. Two of the four ceiling-tied operators (op024, op095) show this transition clearly. Score variance was partly driven by <em>discovering</em> an advanced workflow partway through. This is a knowledge asymmetry we should directly address in onboarding next time.</p>

    <h3>For content design</h3>
    <p><strong>Difficulty calibration held.</strong> Mean solve rates fell monotonically easy → medium → hard → expert. The designers' tiers matched observed difficulty.</p>
    <p><strong>M3 Lab was genuine difficulty.</strong> Conditional solve rate (among the ${m.M3 ? m.M3.participants_attempted : 0} who attempted) was ${m.M3 ? Math.round(m.M3.participants_touched / (m.M3.participants_attempted || 1) * 100) : 0}%. This is what content-tier-hard looks like when the infrastructure isn't blocking you: plenty of attempts, some solves, clear gradient.</p>
    <p><strong>Hint 2 = the answer on hard content.</strong> ${d.hint_impact.filter(h => h.lift >= 0.8).length} challenges had +80% lift for hint unlockers. If the intent is "nudge not answer," Hint 2 on hard content needs rewriting.</p>

    <h3>For the platform</h3>
    <p><strong>Rate-limit config needs tuning for agentic events.</strong> ${fmtNum(s.ratelimited_total)} rejections (~${Math.round(s.ratelimited_total/s.submissions_total*100)}% of all submissions), concentrated in the Claude-drives-submission cluster. Higher per-user caps + distinguish "many wrong flags in a burst" (warn/backoff) from "many submissions overall" (allow).</p>

    <h3>For next event</h3>
    <p><strong>Pre-event: do end-to-end smoketests of every pivot-gated mission.</strong> Every splice, every network transition, every inter-container route. The splice-watcher bug was caught by no smoketest because no one ran the M4 → M5 transition against a live range before the event. A single integration test "solve Lights Out, confirm kali reaches bunker within 30s" would have caught it.</p>
    <p><strong>Build the stuck-signature detector into the dashboard.</strong> Per-challenge near-answer regex. When N≥2 operators have ≥5 near-answer submissions and 0 solves, raise an alert. We had the signal; we weren't looking for it.</p>
    <p><strong>Document the Claude-submits workflow up-front.</strong> Add an example to the AI-Assistant CTFd page. Don't leave it as hidden advanced knowledge — discoverability was a large source of variance.</p>
    <p><strong>Pareto is less top-heavy than classical CTFs.</strong> Top 10% captured ${fmtPct(d.pareto.top_10pct_points_share)} of points. When everyone has Claude, the distribution flattens. Plan for richer mid-band engagement, fewer dramatic top-heavy outcomes.</p>
  `;
}
