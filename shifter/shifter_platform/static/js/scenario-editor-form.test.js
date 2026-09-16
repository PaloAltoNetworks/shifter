// Tests for the scenario editor create/edit form: HTML/escaping helpers, the
// dynamic instance and subnet builders, add/remove row handlers, the
// domain-controller config toggles, and submit-time JSON serialization.
//
// The source reads its initial data from the #instances-data / #subnets-data
// json_script payloads and wires the submit handler at module load, so each
// test builds the DOM fixture first, then requires the module fresh.

function buildFixture(instances, subnets) {
    return `
        <form id="scenarioForm">
            <input type="hidden" id="instances_json">
            <input type="hidden" id="subnets_json">
            <div id="instances-container"></div>
            <div id="subnets-container"></div>
        </form>
        <script type="application/json" id="instances-data">${JSON.stringify(instances || [])}</script>
        <script type="application/json" id="subnets-data">${JSON.stringify(subnets || [])}</script>
    `;
}

function load(instances, subnets) {
    jest.resetModules();
    document.body.innerHTML = buildFixture(instances, subnets);
    return require('./scenario-editor-form.js');
}

describe('scenario-editor-form', () => {
    beforeEach(() => {
        // Silence jsdom's "Not implemented: form submission" navigation noise.
        jest.spyOn(console, 'error').mockImplementation(() => {});
        globalThis.alert = jest.fn();
    });

    afterEach(() => {
        jest.resetModules();
        jest.restoreAllMocks();
    });

    describe('helpers', () => {
        test('escapeHtml escapes markup-significant characters', () => {
            const mod = load([], []);
            expect(mod.escapeHtml('<script>')).toBe('&lt;script&gt;');
            expect(mod.escapeHtml('a & b')).toBe('a &amp; b');
        });

        test('parseNameList splits, trims, and drops empties', () => {
            const mod = load([], []);
            expect(mod.parseNameList('a, b ,, c')).toEqual(['a', 'b', 'c']);
            expect(mod.parseNameList('')).toEqual([]);
        });

        test('buildInstanceDcConfigHtml returns empty when not a domain controller', () => {
            const mod = load([], []);
            expect(mod.buildInstanceDcConfigHtml({ domain_controller: false }, 0)).toBe('');
        });

        test('buildInstanceDcConfigHtml falls back to defaults when dc_config is missing', () => {
            const mod = load([], []);
            const html = mod.buildInstanceDcConfigHtml({ domain_controller: true, dc_config: null }, 0);
            expect(html).toContain('internal.shifter');
            expect(html).toContain('INTSHIFTER');
        });
    });

    describe('renderInstances', () => {
        test('renders a card per instance with selected role/os, checkboxes, and a DC panel', () => {
            load(
                [
                    {
                        name: 'box<1>',
                        role: 'attacker',
                        os_type: 'kali',
                        xdr_agent: true,
                        domain_controller: true,
                        join_domain: true,
                        dc_config: { domain_name: 'corp.local', netbios_name: 'CORP' },
                    },
                    {
                        name: 'plain',
                        role: 'victim',
                        os_type: 'windows',
                        domain_controller: false,
                    },
                ],
                []
            );
            const container = document.getElementById('instances-container');

            expect(container.querySelectorAll('.instance-card').length).toBe(2);
            expect(container.querySelector('#instance-0-role').value).toBe('attacker');
            expect(container.querySelector('#instance-0-os-type').value).toBe('kali');
            expect(container.querySelector('#instance-0-xdr-agent').checked).toBe(true);
            // The name is HTML-escaped into the value attribute.
            expect(container.querySelector('#instance-0-name').value).toBe('box<1>');
            // Only the first (domain_controller) instance renders a DC config panel.
            expect(container.querySelectorAll('.dc-config-panel').length).toBe(1);
            expect(container.querySelector('#instance-0-domain-name').value).toBe('corp.local');
            expect(container.querySelector('#instance-0-netbios-name').value).toBe('CORP');
        });
    });

    describe('renderSubnets', () => {
        test('lists available instance names in the help text', () => {
            load(
                [{ name: 'a' }, { name: 'b' }],
                [{ name: 'core', instances: ['a'], connected_to: ['edge'] }]
            );
            const container = document.getElementById('subnets-container');

            expect(container.querySelectorAll('.subnet-card').length).toBe(1);
            expect(container.querySelector('#subnet-0-name').value).toBe('core');
            expect(container.querySelector('#subnet-0-instances').value).toBe('a');
            expect(container.querySelector('#subnet-0-connected-to').value).toBe('edge');
            expect(container.querySelector('.help-text').textContent).toContain('a, b');
        });

        test('prompts to define instances first when none exist', () => {
            load([], [{ name: 'core' }]);
            const container = document.getElementById('subnets-container');
            expect(container.querySelector('.help-text').textContent).toContain('(define instances first)');
        });
    });

    describe('add/remove handlers', () => {
        test('addInstance appends a default instance and re-renders', () => {
            const mod = load([], []);
            mod.addInstance();

            expect(globalThis.instances).toHaveLength(1);
            expect(globalThis.instances[0]).toMatchObject({ role: 'victim', os_type: 'windows' });
            expect(document.querySelectorAll('#instances-container .instance-card')).toHaveLength(1);
        });

        test('removeInstance drops the instance at the given index', () => {
            const mod = load([{ name: 'a' }, { name: 'b' }], []);
            mod.removeInstance(0);

            expect(globalThis.instances).toHaveLength(1);
            expect(globalThis.instances[0].name).toBe('b');
            expect(document.querySelectorAll('#instances-container .instance-card')).toHaveLength(1);
        });

        test('addSubnet appends a default subnet and re-renders', () => {
            const mod = load([], []);
            mod.addSubnet();

            expect(globalThis.subnets).toHaveLength(1);
            expect(globalThis.subnets[0]).toEqual({ name: '', instances: [], connected_to: [] });
            expect(document.querySelectorAll('#subnets-container .subnet-card')).toHaveLength(1);
        });

        test('removeSubnet drops the subnet at the given index', () => {
            const mod = load([], [{ name: 'core' }, { name: 'edge' }]);
            mod.removeSubnet(1);

            expect(globalThis.subnets).toHaveLength(1);
            expect(globalThis.subnets[0].name).toBe('core');
        });
    });

    describe('domain controller config', () => {
        test('handleDCChange creates, preserves, then clears dc_config', () => {
            const mod = load([{ name: 'dc', domain_controller: false, dc_config: null }], []);

            mod.handleDCChange(0, true);
            expect(globalThis.instances[0].domain_controller).toBe(true);
            expect(globalThis.instances[0].dc_config).toEqual({
                domain_name: 'internal.shifter',
                netbios_name: 'INTSHIFTER',
            });

            // Re-enabling with an existing config must not overwrite it.
            globalThis.instances[0].dc_config.domain_name = 'kept.local';
            mod.handleDCChange(0, true);
            expect(globalThis.instances[0].dc_config.domain_name).toBe('kept.local');

            mod.handleDCChange(0, false);
            expect(globalThis.instances[0].domain_controller).toBe(false);
            expect(globalThis.instances[0].dc_config).toBeNull();
        });

        test('updateDCConfig lazily creates dc_config then updates the field', () => {
            const mod = load([{ name: 'dc', dc_config: null }], []);

            mod.updateDCConfig(0, 'domain_name', 'x.local');
            expect(globalThis.instances[0].dc_config).toEqual({ domain_name: 'x.local', netbios_name: '' });

            mod.updateDCConfig(0, 'netbios_name', 'XLOCAL');
            expect(globalThis.instances[0].dc_config.netbios_name).toBe('XLOCAL');
        });
    });

    describe('submit serialization', () => {
        test('writes the instances/subnets JSON into the hidden inputs', () => {
            load([{ name: 'a', role: 'victim', os_type: 'windows' }], [{ name: 'core' }]);
            const form = document.getElementById('scenarioForm');

            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

            expect(document.getElementById('instances_json').value).toBe(JSON.stringify(globalThis.instances));
            expect(document.getElementById('subnets_json').value).toBe(JSON.stringify(globalThis.subnets));
            expect(globalThis.alert).not.toHaveBeenCalled();
        });

        test('prevents submission and alerts when serialization throws', () => {
            load([{ name: 'a' }], []);
            // A circular reference makes JSON.stringify throw.
            const circular = {};
            circular.self = circular;
            globalThis.instances.push(circular);
            const form = document.getElementById('scenarioForm');
            const evt = new Event('submit', { bubbles: true, cancelable: true });

            form.dispatchEvent(evt);

            expect(evt.defaultPrevented).toBe(true);
            expect(globalThis.alert).toHaveBeenCalledWith(expect.stringContaining('Error preparing form data'));
        });
    });
});
