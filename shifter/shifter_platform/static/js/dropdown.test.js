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
