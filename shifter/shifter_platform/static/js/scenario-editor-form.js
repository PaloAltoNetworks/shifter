// Scenario editor create/edit form: dynamic instance and subnet builders.
//
// Extracted from the inline <script> block in
// templates/scenario_editor/form.html so the template stays within Sonar's
// Web:LongJavaScriptCheck limit. Initial data is read from the
// #instances-data / #subnets-data json_script payloads. Functions and the
// working arrays are exposed on globalThis because the rows this script
// renders wire their events through inline on* handlers.

var instances = [];
var subnets = [];
var instancesEl = document.getElementById('instances-data');
var subnetsEl = document.getElementById('subnets-data');
if (instancesEl) instances = JSON.parse(instancesEl.textContent);
if (subnetsEl) subnets = JSON.parse(subnetsEl.textContent);

var ROLES = ['attacker', 'victim', 'dc', 'ngfw'];
var OS_TYPES = ['kali', 'ubuntu', 'windows', 'from_agent', 'panos'];

function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function parseNameList(value) {
    return value.split(',').map(function(s) {
        return s.trim();
    }).filter(Boolean);
}

function buildInstanceRoleOptions(inst) {
    return ROLES.map(function(r) {
        return '<option value="' + escapeHtml(r) + '" '
            + (inst.role === r ? 'selected' : '') + '>'
            + escapeHtml(r) + '</option>';
    }).join('');
}

function buildInstanceOsOptions(inst) {
    return OS_TYPES.map(function(o) {
        return '<option value="' + escapeHtml(o) + '" '
            + (inst.os_type === o ? 'selected' : '') + '>'
            + escapeHtml(o) + '</option>';
    }).join('');
}

function buildInstanceFieldsHtml(inst, idx) {
    return `
            <div class="inline-fields">
                <div class="form-group form-group-compact">
                    <label for="instance-${idx}-name">Name</label>
                    <input type="text"
                           id="instance-${idx}-name"
                           class="form-input"
                           value="${escapeHtml(inst.name || '')}"
                           onchange="instances[${idx}].name = this.value"
                           placeholder="Instance name"
                           required>
                </div>
                <div class="form-group form-group-compact">
                    <label for="instance-${idx}-role">Role</label>
                    <select id="instance-${idx}-role"
                            class="form-select"
                            onchange="instances[${idx}].role = this.value">
                        ${buildInstanceRoleOptions(inst)}
                    </select>
                </div>
                <div class="form-group form-group-compact">
                    <label for="instance-${idx}-os-type">OS Type</label>
                    <select id="instance-${idx}-os-type"
                            class="form-select"
                            onchange="instances[${idx}].os_type = this.value">
                        ${buildInstanceOsOptions(inst)}
                    </select>
                </div>
            </div>`;
}

function buildInstanceCheckboxesHtml(inst, idx) {
    return `
            <div class="inline-fields inline-fields-mt">
                <div class="form-checkbox">
                    <input type="checkbox"
                           id="instance-${idx}-xdr-agent"
                           ${inst.xdr_agent ? 'checked' : ''}
                           onchange="instances[${idx}].xdr_agent = this.checked">
                    <label class="form-label-sm" for="instance-${idx}-xdr-agent">XDR Agent</label>
                </div>
                <div class="form-checkbox">
                    <input type="checkbox"
                           id="instance-${idx}-domain-controller"
                           ${inst.domain_controller ? 'checked' : ''}
                           onchange="handleDCChange(${idx}, this.checked)">
                    <label class="form-label-sm" for="instance-${idx}-domain-controller">Domain Controller</label>
                </div>
                <div class="form-checkbox">
                    <input type="checkbox"
                           id="instance-${idx}-join-domain"
                           ${inst.join_domain ? 'checked' : ''}
                           onchange="instances[${idx}].join_domain = this.checked">
                    <label class="form-label-sm" for="instance-${idx}-join-domain">Join Domain</label>
                </div>
            </div>`;
}

function buildInstanceDcConfigHtml(inst, idx) {
    if (!inst.domain_controller) {
        return '';
    }
    return `
            <div class="dc-config-panel">
                <div class="inline-fields">
                    <div class="form-group form-group-compact">
                        <label for="instance-${idx}-domain-name">Domain Name</label>
                        <input type="text"
                               id="instance-${idx}-domain-name"
                               class="form-input"
                               value="${escapeHtml(inst.dc_config?.domain_name || 'internal.shifter')}"
                               onchange="updateDCConfig(${idx}, 'domain_name', this.value)"
                               placeholder="internal.shifter">
                    </div>
                    <div class="form-group form-group-compact">
                        <label for="instance-${idx}-netbios-name">NetBIOS Name</label>
                        <input type="text"
                               id="instance-${idx}-netbios-name"
                               class="form-input"
                               value="${escapeHtml(inst.dc_config?.netbios_name || 'INTSHIFTER')}"
                               onchange="updateDCConfig(${idx}, 'netbios_name', this.value)"
                               placeholder="INTSHIFTER">
                    </div>
                </div>
            </div>`;
}

function buildInstanceCardHtml(inst, idx) {
    return `
            <div class="instance-card-header">
                <strong class="instance-card-title">Instance ${idx + 1}</strong>
                <button type="button"
                        class="btn btn-danger btn-remove-sm"
                        onclick="removeInstance(${idx})">
                    Remove
                </button>
            </div>
            ${buildInstanceFieldsHtml(inst, idx)}
            ${buildInstanceCheckboxesHtml(inst, idx)}
            ${buildInstanceDcConfigHtml(inst, idx)}`;
}

function renderInstances() {
    var container = document.getElementById('instances-container');
    container.innerHTML = '';

    instances.forEach(function(inst, idx) {
        var card = document.createElement('div');
        card.className = 'instance-card';
        card.innerHTML = buildInstanceCardHtml(inst, idx);
        container.appendChild(card);
    });
}

function buildSubnetCardHtml(subnet, idx, instanceNames) {
    return `
            <div class="instance-card-header">
                <strong class="instance-card-title">Subnet ${idx + 1}</strong>
                <button type="button"
                        class="btn btn-danger btn-remove-sm"
                        onclick="removeSubnet(${idx})">
                    Remove
                </button>
            </div>
            <div class="form-group form-group-compact">
                <label for="subnet-${idx}-name">Subnet Name</label>
                <input type="text"
                       id="subnet-${idx}-name"
                       class="form-input"
                       value="${escapeHtml(subnet.name || '')}"
                       onchange="subnets[${idx}].name = this.value"
                       placeholder="core"
                       required>
            </div>
            <div class="form-group form-group-compact">
                <label for="subnet-${idx}-instances">Instances (comma-separated names)</label>
                <input type="text"
                       id="subnet-${idx}-instances"
                       class="form-input"
                       value="${escapeHtml((subnet.instances || []).join(', '))}"
                       onchange="subnets[${idx}].instances = parseNameList(this.value)"
                       placeholder="${escapeHtml(instanceNames.join(', '))}">
                <div class="help-text">Available: ${escapeHtml(instanceNames.join(', ') || '(define instances first)')}
                </div>
            </div>
            <div class="form-group form-group-compact">
                <label for="subnet-${idx}-connected-to">Connected To (comma-separated subnet names)</label>
                <input type="text"
                       id="subnet-${idx}-connected-to"
                       class="form-input"
                       value="${escapeHtml((subnet.connected_to || []).join(', '))}"
                       onchange="subnets[${idx}].connected_to = parseNameList(this.value)"
                       placeholder="other_subnet">
            </div>`;
}

function renderSubnets() {
    var container = document.getElementById('subnets-container');
    container.innerHTML = '';

    var instanceNames = instances.map(function(i) { return i.name; }).filter(Boolean);

    subnets.forEach(function(subnet, idx) {
        var card = document.createElement('div');
        card.className = 'subnet-card';
        card.innerHTML = buildSubnetCardHtml(subnet, idx, instanceNames);
        container.appendChild(card);
    });
}

function addInstance() {
    instances.push({
        name: '',
        role: 'victim',
        os_type: 'windows',
        xdr_agent: false,
        domain_controller: false,
        join_domain: false,
        dc_config: null,
    });
    renderInstances();
}

function removeInstance(idx) {
    instances.splice(idx, 1);
    renderInstances();
}

function addSubnet() {
    subnets.push({
        name: '',
        instances: [],
        connected_to: [],
    });
    renderSubnets();
}

function removeSubnet(idx) {
    subnets.splice(idx, 1);
    renderSubnets();
}

function handleDCChange(idx, checked) {
    // idx is a trusted numeric array index produced by renderInstances().
    var inst = instances[idx]; // eslint-disable-line security/detect-object-injection
    inst.domain_controller = checked;
    if (checked && !inst.dc_config) {
        inst.dc_config = { domain_name: 'internal.shifter', netbios_name: 'INTSHIFTER' };
    } else if (!checked) {
        inst.dc_config = null;
    }
    renderInstances();
}

function updateDCConfig(idx, field, value) {
    // idx is a trusted numeric array index; field is a fixed DC config key.
    var inst = instances[idx]; // eslint-disable-line security/detect-object-injection
    if (!inst.dc_config) {
        inst.dc_config = { domain_name: '', netbios_name: '' };
    }
    inst.dc_config[field] = value; // eslint-disable-line security/detect-object-injection
}

// Serialize data before form submission
document.getElementById('scenarioForm').addEventListener('submit', function(e) {
    try {
        document.getElementById('instances_json').value = JSON.stringify(instances);
        document.getElementById('subnets_json').value = JSON.stringify(subnets);
    } catch (err) {
        e.preventDefault();
        alert('Error preparing form data: ' + err.message);
    }
});

// Expose the working arrays and handlers for the inline on* attributes that
// the rendered instance/subnet rows rely on.
globalThis.instances = instances;
globalThis.subnets = subnets;
globalThis.parseNameList = parseNameList;
globalThis.addInstance = addInstance;
globalThis.removeInstance = removeInstance;
globalThis.addSubnet = addSubnet;
globalThis.removeSubnet = removeSubnet;
globalThis.handleDCChange = handleDCChange;
globalThis.updateDCConfig = updateDCConfig;

// Initial render
renderInstances();
renderSubnets();

// Expose for testing
if (typeof module !== 'undefined' && module.exports) { // eslint-disable-line no-undef
    module.exports = { // eslint-disable-line no-undef
        escapeHtml: escapeHtml,
        parseNameList: parseNameList,
        buildInstanceRoleOptions: buildInstanceRoleOptions,
        buildInstanceOsOptions: buildInstanceOsOptions,
        buildInstanceFieldsHtml: buildInstanceFieldsHtml,
        buildInstanceCheckboxesHtml: buildInstanceCheckboxesHtml,
        buildInstanceDcConfigHtml: buildInstanceDcConfigHtml,
        buildInstanceCardHtml: buildInstanceCardHtml,
        renderInstances: renderInstances,
        buildSubnetCardHtml: buildSubnetCardHtml,
        renderSubnets: renderSubnets,
        addInstance: addInstance,
        removeInstance: removeInstance,
        addSubnet: addSubnet,
        removeSubnet: removeSubnet,
        handleDCChange: handleDCChange,
        updateDCConfig: updateDCConfig,
    };
}
