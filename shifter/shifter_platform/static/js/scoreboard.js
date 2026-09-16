// CTF participant scoreboard: manual/auto refresh toggle and live table
// rebuild. Extracted from the inline <script> in
// templates/ctf/participant/scoreboard.html so the template stays
// within Sonar Web:LongJavaScriptCheck limits. Behavior is unchanged;
// the scoreboard API URL, own-row solve-history URL, and participant id
// are read from the #scoreboard-config element's data-* attributes.

var autoRefreshInterval = null;
// Own-row solve-history link (issue #521). Only the current participant's row
// is linkable; empty when the participant is unresolved.
var solveHistoryUrl = "";
var scoreboardUrl = "";
var participantId = "";

function clearChildren(el) {
    while (el.firstChild) {
        el.firstChild.remove();
    }
}

function refreshScoreboard() {
    var btn = document.getElementById('refresh-btn');

    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
        btn.textContent = 'Auto-Refresh: Off';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-outline-primary');
        return;
    }

    btn.textContent = 'Auto-Refresh: On';
    btn.classList.remove('btn-outline-primary');
    btn.classList.add('btn-primary');

    autoRefreshInterval = setInterval(function() {
        fetchScoreboard();
    }, 15000);

    fetchScoreboard();
}

// Organizer hid the scoreboard mid-event: stop polling, clear the table,
// and show a placeholder banner.
function showHiddenBanner() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    var tbody = document.getElementById('scoreboard-body');
    if (tbody) { clearChildren(tbody); }
    var table = document.getElementById('scoreboard-table');
    if (table) { table.style.display = 'none'; }
    if (!document.getElementById('hidden-banner')) {
        var container = document.querySelector('.container-fluid');
        var hiddenDiv = document.createElement('div');
        hiddenDiv.id = 'hidden-banner';
        hiddenDiv.className = 'card';
        var body = document.createElement('div');
        body.className = 'card-body text-center py-5';
        var h5 = document.createElement('h5');
        h5.className = 'text-muted mb-2';
        h5.textContent = 'Scoreboard Hidden';
        var p = document.createElement('p');
        p.className = 'text-muted mb-0';
        p.textContent = 'The scoreboard is not yet available. The organizer will make it visible when ready.';
        body.appendChild(h5);
        body.appendChild(p);
        hiddenDiv.appendChild(body);
        container.appendChild(hiddenDiv);
    }
    var btn = document.getElementById('refresh-btn');
    if (btn) btn.style.display = 'none';
}

function updateFreezeBanner(frozen) {
    var banner = document.getElementById('freeze-banner');
    if (frozen && !banner) {
        banner = document.createElement('div');
        banner.id = 'freeze-banner';
        banner.className = 'alert alert-info mb-4';
        banner.textContent = 'Scoreboard is now frozen. Your own score continues to update.';
        var container = document.querySelector('.container-fluid');
        var card = container.querySelector('.card');
        card.before(banner);
    }
    if (banner) {
        banner.style.display = frozen ? '' : 'none';
    }
}

function fetchScoreboard() {
    return fetch(scoreboardUrl)
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (data.scoreboard_hidden) {
            showHiddenBanner();
            return;
        }
        if (data.rankings) {
            rebuildScoreboardTable(data.rankings, data.team_mode);
        }
        updateFreezeBanner(data.frozen);
    })
    .catch(function(err) {
        console.error('Failed to refresh scoreboard:', err);
    });
}

function buildRankCell(entry) {
    var tdRank = document.createElement('td');
    if (entry.rank <= 3) {
        var strong = document.createElement('strong');
        strong.textContent = entry.rank;
        tdRank.appendChild(strong);
    } else {
        tdRank.textContent = entry.rank;
    }
    return tdRank;
}

function buildNameCell(entry, isCurrentUser) {
    var tdName = document.createElement('td');
    var nameStrong = document.createElement('strong');
    nameStrong.textContent = entry.name;
    if (isCurrentUser && solveHistoryUrl) {
        var nameLink = document.createElement('a');
        nameLink.href = solveHistoryUrl;
        nameLink.appendChild(nameStrong);
        tdName.appendChild(nameLink);
    } else {
        tdName.appendChild(nameStrong);
    }
    if (isCurrentUser) {
        var badge = document.createElement('span');
        badge.className = 'badge bg-primary ms-1';
        badge.textContent = 'You';
        tdName.appendChild(badge);
    }
    return tdName;
}

function buildTextCell(value) {
    var td = document.createElement('td');
    td.textContent = value;
    return td;
}

function buildStrongCell(value) {
    var td = document.createElement('td');
    var strong = document.createElement('strong');
    strong.textContent = value;
    td.appendChild(strong);
    return td;
}

function buildScoreboardRow(entry, teamMode) {
    var isCurrentUser = !teamMode && (String(entry.participant_id) === String(participantId));

    var tr = document.createElement('tr');
    if (isCurrentUser) tr.className = 'table-active';

    tr.appendChild(buildRankCell(entry));
    tr.appendChild(buildNameCell(entry, isCurrentUser));
    if (teamMode) {
        tr.appendChild(buildTextCell(entry.member_count));
    }
    tr.appendChild(buildStrongCell(entry.score));
    tr.appendChild(buildTextCell(entry.solve_count));
    tr.appendChild(buildTextCell(entry.last_solve || '-'));

    return tr;
}

function rebuildScoreboardTable(rankings, teamMode) {
    var tbody = document.getElementById('scoreboard-body');
    if (!tbody) return;

    clearChildren(tbody);

    rankings.forEach(function (entry) {
        tbody.appendChild(buildScoreboardRow(entry, teamMode));
    });
}

function initScoreboard() {
    var cfg = document.getElementById('scoreboard-config');
    if (!cfg) return;
    solveHistoryUrl = cfg.dataset.solveHistoryUrl || "";
    scoreboardUrl = cfg.dataset.scoreboardUrl || "";
    participantId = cfg.dataset.participantId || "";
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initScoreboard);
} else {
    initScoreboard();
}

globalThis.refreshScoreboard = refreshScoreboard;

// Expose for testing
if (typeof module !== 'undefined' && module.exports) { // eslint-disable-line no-undef
    module.exports = { // eslint-disable-line no-undef
        refreshScoreboard: refreshScoreboard,
        fetchScoreboard: fetchScoreboard,
        rebuildScoreboardTable: rebuildScoreboardTable,
        showHiddenBanner: showHiddenBanner,
        updateFreezeBanner: updateFreezeBanner,
        initScoreboard: initScoreboard,
    };
}
