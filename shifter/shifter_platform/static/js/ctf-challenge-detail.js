// CTF participant challenge-detail page interactions: flag submission,
// progressive hints, challenge-file downloads, and challenge rating.
//
// Extracted from the inline <script> block in
// templates/ctf/participant/challenge_detail.html so the template stays
// within Sonar's Web:LongJavaScriptCheck and Web:FileLengthCheck limits.
// Django-interpolated URLs and challenge values are passed in via the
// #ctf-challenge-detail-config json_script payload.

function getCookie(name) {
    if (!document.cookie) {
        return null;
    }
    const prefix = name + '=';
    const match = document.cookie
        .split(';')
        .map(function (part) { return part.trim(); })
        .find(function (part) { return part.startsWith(prefix); });
    return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function readConfig() {
    const el = document.getElementById('ctf-challenge-detail-config');
    return el ? JSON.parse(el.textContent) : {};
}

const config = readConfig();

const ALERT_DANGER_CLASS = 'alert alert-danger mb-3';
const GENERIC_ERROR = 'An error occurred. Please try again.';

function submitFlag(e) {
    e.preventDefault();
    const flag = document.getElementById('flag-input').value;
    const btn = document.getElementById('submit-btn');
    const resultDiv = document.getElementById('submit-result');

    btn.disabled = true;
    btn.textContent = 'Submitting...';

    fetch(config.submitFlagUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ flag: flag }),
    })
    .then(function (response) {
        return response.json().then(function (data) {
            return { response: response, data: data };
        });
    })
    .then(function (result) {
        const response = result.response;
        const data = result.data;
        resultDiv.classList.remove('d-none');
        if (response.status === 429) {
            resultDiv.className = 'alert alert-warning mb-3';
            const retrySecs = data.retry_after_seconds || response.headers.get('Retry-After');
            let msg = '<strong>Please wait.</strong> You are submitting too quickly.';
            if (retrySecs) {
                msg += ' Try again in ' + retrySecs + ' seconds.';
            }
            resultDiv.innerHTML = msg;
            btn.disabled = false;
            btn.textContent = 'Submit';
        } else if (response.ok && data.correct) {
            resultDiv.className = 'alert alert-success mb-3';
            resultDiv.innerHTML = '<strong>Correct!</strong> You earned ' + data.points_awarded + ' points.';
            document.getElementById('flag-form').style.display = 'none';
            setTimeout(function () { location.reload(); }, 1500);
        } else if (response.ok) {
            resultDiv.className = ALERT_DANGER_CLASS;
            let msg = '<strong>Incorrect.</strong>';
            if (data.message) {
                msg += ' ' + data.message;
            }
            resultDiv.innerHTML = msg;
            btn.disabled = false;
            btn.textContent = 'Submit';
            document.getElementById('flag-input').value = '';
        } else {
            resultDiv.className = ALERT_DANGER_CLASS;
            resultDiv.textContent = data.error || GENERIC_ERROR;
            btn.disabled = false;
            btn.textContent = 'Submit';
        }
    })
    .catch(function () {
        resultDiv.classList.remove('d-none');
        resultDiv.className = ALERT_DANGER_CLASS;
        resultDiv.textContent = GENERIC_ERROR;
        btn.disabled = false;
        btn.textContent = 'Submit';
    });

    return false;
}

function useHint(hintId, hintPenalty) {
    const challengePoints = config.challengePoints;
    const currentPenalty = config.totalHintPenalty;
    const currentPenaltyCapped = Math.min(currentPenalty, 100);
    const currentValue = Math.max(1, challengePoints - Math.floor(challengePoints * currentPenaltyCapped / 100));
    const projectedPenalty = Math.min(currentPenalty + (hintPenalty || 0), 100);
    const pointsAfter = Math.max(1, challengePoints - Math.floor(challengePoints * projectedPenalty / 100));
    const cost = currentValue - pointsAfter;

    let msg = 'Reveal this hint?\n\n';
    if (hintPenalty > 0) {
        msg += 'Cost: ' + hintPenalty + '% penalty (-' + cost + ' pts)\n';
        msg += 'Challenge value after: ' + pointsAfter + ' / ' + challengePoints + ' pts\n';
    }
    if (projectedPenalty >= 100) {
        msg += '\n⚠ WARNING: This will reduce the challenge to its minimum value (1 pt)!';
    }
    msg += '\nThis action cannot be undone.';

    if (!confirm(msg)) {
        return;
    }

    fetch(config.useHintUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ hint_id: hintId }),
    })
    .then(function (response) { return response.json(); })
    .then(function (data) {
        if (data.text) {
            location.reload();
        } else if (data.error) {
            alert(data.error);
        }
    })
    .catch(function () {
        alert(GENERIC_ERROR);
    });
}

function downloadFile(apiUrl) {
    fetch(apiUrl, { headers: { 'X-CSRFToken': getCookie('csrftoken') } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.url) { globalThis.location.href = data.url; }
            else if (data.error) { alert(data.error); }
        })
        .catch(function () { alert('Download failed.'); });
}

document.querySelectorAll('[data-download-url]').forEach(function (link) {
    link.addEventListener('click', function (event) {
        event.preventDefault();
        downloadFile(link.dataset.downloadUrl);
    });
});

function rateChallenge(value) {
    const resultDiv = document.getElementById('rating-result');

    fetch(config.rateChallengeUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ value: value }),
    })
    .then(function (response) { return response.json(); })
    .then(function (data) {
        if (data.error) {
            resultDiv.classList.remove('d-none');
            resultDiv.className = ALERT_DANGER_CLASS;
            resultDiv.textContent = data.error;
        } else {
            resultDiv.classList.remove('d-none');
            resultDiv.className = 'alert alert-success mb-3';
            resultDiv.textContent = 'Rated ' + value + '/5. Thanks!';
            // Update button styles
            const buttons = document.querySelectorAll('.btn-group .btn');
            buttons.forEach(function (btn, i) {
                btn.className = (i + 1 === value) ? 'btn btn-warning btn-sm' : 'btn btn-outline-warning btn-sm';
            });
        }
    })
    .catch(function () {
        resultDiv.classList.remove('d-none');
        resultDiv.className = ALERT_DANGER_CLASS;
        resultDiv.textContent = 'Rating failed. Please try again.';
    });
}

globalThis.submitFlag = submitFlag;
globalThis.useHint = useHint;
globalThis.rateChallenge = rateChallenge;
