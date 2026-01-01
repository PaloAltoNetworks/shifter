describe('XdrDropdown explicit init', () => {
    const buildDropdownMarkup = () => `
        <div class="xdr-dropdown" id="test-dropdown">
            <input type="hidden" name="value">
            <button type="button" class="xdr-dropdown-trigger">
                <span class="xdr-dropdown-value placeholder">Select</span>
            </button>
            <div class="xdr-dropdown-panel">
                <ul class="xdr-dropdown-items">
                    <li class="xdr-dropdown-item" data-value="1">One</li>
                </ul>
            </div>
        </div>
    `;

    const loadModule = () => {
        require('./xdr-dropdown.js');
        return window.XdrDropdown;
    };

    beforeEach(() => {
        jest.resetModules();
        delete window.XdrDropdown;
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
        const XdrDropdown = loadModule();

        expect(XdrDropdown.init).toBeDefined();

        const dropdown = document.getElementById('test-dropdown');
        const instance = XdrDropdown.init(dropdown);

        expect(dropdown._xdrDropdown).toBe(instance);
        expect(instance.items).toHaveLength(1);

        const itemsContainer = dropdown.querySelector('.xdr-dropdown-items');
        const newItem = document.createElement('li');
        newItem.className = 'xdr-dropdown-item';
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
        const XdrDropdown = loadModule();

        const dropdown = document.getElementById('test-dropdown');
        const first = XdrDropdown.init(dropdown);
        const second = XdrDropdown.init(dropdown);

        expect(second).toBe(first);
    });
});
