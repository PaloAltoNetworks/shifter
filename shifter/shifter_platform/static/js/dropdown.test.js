describe('ShifterDropdown explicit init', () => {
    const buildDropdownMarkup = () => `
        <div class="shifter-dropdown" id="test-dropdown">
            <input type="hidden" name="value">
            <button type="button" class="shifter-dropdown-trigger">
                <span class="shifter-dropdown-value placeholder">Select</span>
            </button>
            <div class="shifter-dropdown-panel">
                <ul class="shifter-dropdown-items">
                    <li class="shifter-dropdown-item" data-value="1">One</li>
                </ul>
            </div>
        </div>
    `;

    const loadModule = () => {
        require('./dropdown.js');
        return globalThis.ShifterDropdown;
    };

    beforeEach(() => {
        jest.resetModules();
        delete globalThis.ShifterDropdown;
        document.body.innerHTML = '';
    });

    test('does not register DOMContentLoaded auto-init', () => {
        const addListenerSpy = jest.spyOn(document, 'addEventListener');

        loadModule();

        expect(addListenerSpy).not.toHaveBeenCalledWith('DOMContentLoaded', expect.any(Function));
        addListenerSpy.mockRestore();
    });

    test('wires aria-labelledby from preceding label in form-group', () => {
        document.body.innerHTML = `
            <div class="form-group">
                <label class="form-label">Scenario</label>
                <div class="shifter-dropdown" id="scenario-dropdown">
                    <input type="hidden" id="scenario-select-value">
                    <button type="button" class="shifter-dropdown-trigger">
                        <span class="shifter-dropdown-value placeholder">Select</span>
                    </button>
                    <div class="shifter-dropdown-panel">
                        <ul class="shifter-dropdown-items">
                            <li class="shifter-dropdown-item" data-value="1">One</li>
                        </ul>
                    </div>
                </div>
            </div>
        `;
        const ShifterDropdown = loadModule();
        const dropdown = document.getElementById('scenario-dropdown');
        const trigger = dropdown.querySelector('.shifter-dropdown-trigger');
        const label = dropdown.parentElement.querySelector('label');

        ShifterDropdown.init(dropdown);

        expect(label.id).toBeTruthy();
        expect(trigger.getAttribute('aria-labelledby')).toBe(label.id);
        expect(trigger.getAttribute('aria-haspopup')).toBe('listbox');
        expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });

    test('sets aria-expanded when dropdown opens and closes', () => {
        document.body.innerHTML = `
            <div class="form-group">
                <label class="form-label" id="type-label">Type</label>
                <div class="shifter-dropdown" id="type-dropdown">
                    <input type="hidden">
                    <button type="button" class="shifter-dropdown-trigger" id="type-dropdown-trigger">
                        <span class="shifter-dropdown-value placeholder">Select</span>
                    </button>
                    <div class="shifter-dropdown-panel">
                        <ul class="shifter-dropdown-items">
                            <li class="shifter-dropdown-item" data-value="1">One</li>
                        </ul>
                    </div>
                </div>
            </div>
        `;
        const ShifterDropdown = loadModule();
        const dropdown = document.getElementById('type-dropdown');
        const trigger = dropdown.querySelector('.shifter-dropdown-trigger');
        const instance = ShifterDropdown.init(dropdown);

        instance.open();
        expect(trigger.getAttribute('aria-expanded')).toBe('true');

        instance.close();
        expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });

    test('wires aria-labelledby from label matching hidden input id', () => {
        document.body.innerHTML = `
            <div class="form-group">
                <label for="credential_type">Type</label>
                <div class="shifter-dropdown" id="type-dropdown">
                    <input type="hidden" id="credential_type">
                    <button type="button" class="shifter-dropdown-trigger">
                        <span class="shifter-dropdown-value placeholder">Select</span>
                    </button>
                    <div class="shifter-dropdown-panel">
                        <ul class="shifter-dropdown-items">
                            <li class="shifter-dropdown-item" data-value="1">One</li>
                        </ul>
                    </div>
                </div>
            </div>
        `;
        const ShifterDropdown = loadModule();
        const dropdown = document.getElementById('type-dropdown');
        const trigger = dropdown.querySelector('.shifter-dropdown-trigger');
        const label = dropdown.parentElement.querySelector('label');

        ShifterDropdown.init(dropdown);

        expect(label.id).toBeTruthy();
        expect(trigger.getAttribute('aria-labelledby')).toBe(label.id);
    });

    test('sets popup attributes when no label is present', () => {
        document.body.innerHTML = `
            <div class="shifter-dropdown" id="bare-dropdown">
                <input type="hidden">
                <button type="button" class="shifter-dropdown-trigger">
                    <span class="shifter-dropdown-value placeholder">Select</span>
                </button>
                <div class="shifter-dropdown-panel">
                    <ul class="shifter-dropdown-items">
                        <li class="shifter-dropdown-item" data-value="1">One</li>
                    </ul>
                </div>
            </div>
        `;
        const ShifterDropdown = loadModule();
        const dropdown = document.getElementById('bare-dropdown');
        const trigger = dropdown.querySelector('.shifter-dropdown-trigger');

        ShifterDropdown.init(dropdown);

        expect(trigger.getAttribute('aria-labelledby')).toBeNull();
        expect(trigger.getAttribute('aria-haspopup')).toBe('listbox');
        expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });

    test('init caches instance and refreshes items', () => {
        document.body.innerHTML = buildDropdownMarkup();
        const ShifterDropdown = loadModule();

        expect(ShifterDropdown.init).toBeDefined();

        const dropdown = document.getElementById('test-dropdown');
        const instance = ShifterDropdown.init(dropdown);

        expect(dropdown._shifterDropdown).toBe(instance);
        expect(instance.items).toHaveLength(1);

        const itemsContainer = dropdown.querySelector('.shifter-dropdown-items');
        const newItem = document.createElement('li');
        newItem.className = 'shifter-dropdown-item';
        newItem.dataset.value = '2';
        newItem.textContent = 'Two';
        itemsContainer.appendChild(newItem);

        instance.refreshItems();

        expect(instance.items).toHaveLength(2);
        const addedItem = instance.items.find(item => item.dataset.value === '2');
        expect(addedItem).not.toBeNull();
    });

    test('init returns the same instance on repeated calls', () => {
        document.body.innerHTML = buildDropdownMarkup();
        const ShifterDropdown = loadModule();

        const dropdown = document.getElementById('test-dropdown');
        const first = ShifterDropdown.init(dropdown);
        const second = ShifterDropdown.init(dropdown);

        expect(second).toBe(first);
    });
});
