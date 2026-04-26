/**
 * CTF Range Management
 *
 * Handles:
 * - Bulk provisioning all participant ranges
 * - Individual participant range provisioning
 * - Individual participant range destruction
 * - Individual participant range stop/start/restart
 * - Status polling after provisioning
 */

class CTFRangeManager {
    constructor(options) {
        this.csrfToken = options.csrfToken;
        this.provisionAllUrl = options.provisionAllUrl;
        this.rangeListUrl = options.rangeListUrl;
        this.statusPollDelay = options.statusPollDelay || 10000;
        this.statusPollInterval = null;
    }

    init() {
        this._bindProvisionAll();
        this._bindPerParticipantButtons();
    }

    _bindProvisionAll() {
        let btn = document.getElementById('btn-provision-all');
        if (!btn) return;
        btn.addEventListener('click', () => this.provisionAll());
    }

    _bindPerParticipantButtons() {
        let self = this;

        document.querySelectorAll('.btn-provision').forEach(function(btn) {
            btn.addEventListener('click', function() {
                let participantId = this.dataset.participantId;
                self.provisionOne(participantId, this);
            });
        });

        document.querySelectorAll('.btn-destroy').forEach(function(btn) {
            btn.addEventListener('click', function() {
                let participantId = this.dataset.participantId;
                self.destroyOne(participantId, this);
            });
        });

        document.querySelectorAll('.btn-stop').forEach(function(btn) {
            btn.addEventListener('click', function() {
                let participantId = this.dataset.participantId;
                self.stopOne(participantId, this);
            });
        });

        document.querySelectorAll('.btn-start').forEach(function(btn) {
            btn.addEventListener('click', function() {
                let participantId = this.dataset.participantId;
                self.startOne(participantId, this);
            });
        });

        document.querySelectorAll('.btn-restart').forEach(function(btn) {
            btn.addEventListener('click', function() {
                let participantId = this.dataset.participantId;
                self.restartOne(participantId, this);
            });
        });
    }

    async provisionAll() {
        if (!confirm('Provision ranges for all unassigned participants?')) return;

        let btn = document.getElementById('btn-provision-all');
        this._setButtonLoading(btn, 'Provisioning...');

        try {
            let response = await fetch(this.provisionAllUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Provisioning failed'));
                return;
            }

            let msg = 'Provisioned: ' + data.successful + ', Failed: ' + data.failed;
            if (data.errors && data.errors.length > 0) {
                msg += '\n\nErrors:\n';
                data.errors.forEach(function(e) {
                    msg += '- ' + e.error + '\n';
                });
            }
            alert(msg);
            this._reload();
        } catch (err) {
            alert('Error provisioning ranges: ' + err.message);
        } finally {
            this._clearButtonLoading(btn, 'Provision All Ranges');
        }
    }

    async provisionOne(participantId, btn) {
        if (!confirm('Provision a range for this participant?')) return;

        this._setButtonLoading(btn, 'Provisioning...');

        try {
            let url = '/ctf/api/participants/' + participantId + '/range/provision/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Provisioning failed'));
                this._clearButtonLoading(btn, 'Provision');
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error provisioning range: ' + err.message);
            this._clearButtonLoading(btn, 'Provision');
        }
    }

    async destroyOne(participantId, btn) {
        if (!confirm('Destroy this participant\'s range? This cannot be undone.')) return;

        this._setButtonLoading(btn, 'Destroying...');

        try {
            let url = '/ctf/api/participants/' + participantId + '/range/destroy/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || 'Destruction failed'));
                this._clearButtonLoading(btn, 'Destroy');
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error destroying range: ' + err.message);
            this._clearButtonLoading(btn, 'Destroy');
        }
    }

    async stopOne(participantId, btn) {
        if (!confirm('Stop this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'stop', 'Stopping...', 'Stop');
    }

    async startOne(participantId, btn) {
        if (!confirm('Start this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'start', 'Starting...', 'Start');
    }

    async restartOne(participantId, btn) {
        if (!confirm('Restart this participant\'s range?')) return;
        await this._rangeAction(participantId, btn, 'restart', 'Restarting...', 'Restart');
    }

    async _rangeAction(participantId, btn, action, loadingText, fallbackText) {
        this._setButtonLoading(btn, loadingText);

        try {
            let url = '/ctf/api/participants/' + participantId + '/range/' + action + '/';
            let response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Content-Type': 'application/json',
                },
            });

            let data = await response.json();

            if (!response.ok) {
                alert('Error: ' + (data.error || action + ' failed'));
                this._clearButtonLoading(btn, fallbackText);
                return;
            }

            this._reload();
        } catch (err) {
            alert('Error: ' + err.message);
            this._clearButtonLoading(btn, fallbackText);
        }
    }

    _reload() {
        location.reload();
    }

    _setButtonLoading(btn, text) {
        if (!btn) return;
        btn.disabled = true;
        btn.setAttribute('data-original-text', btn.textContent);
        btn.textContent = text;
    }

    _clearButtonLoading(btn, fallbackText) {
        if (!btn) return;
        btn.disabled = false;
        btn.textContent = btn.dataset.originalText || fallbackText;
    }
}

if (typeof globalThis !== 'undefined') {
    globalThis.CTFRangeManager = CTFRangeManager;
}
