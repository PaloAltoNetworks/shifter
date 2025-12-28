/**
 * XDR Custom Dropdown Component
 * Matches Cortex XDR dropdown styling and behavior
 */

class XdrDropdown {
    constructor(element) {
        this.element = element;
        this.trigger = element.querySelector('.xdr-dropdown-trigger');
        this.valueDisplay = element.querySelector('.xdr-dropdown-value');
        this.panel = element.querySelector('.xdr-dropdown-panel');
        this.itemsContainer = element.querySelector('.xdr-dropdown-items');
        this.filterInput = element.querySelector('.xdr-dropdown-filter input');
        this.hiddenInput = element.querySelector('input[type="hidden"]');

        // Defensive: ensure required elements exist
        if (!this.trigger || !this.itemsContainer) {
            console.warn('XdrDropdown: Missing required elements, skipping init');
            return;
        }

        this.items = Array.from(this.itemsContainer.querySelectorAll('.xdr-dropdown-item'));
        this.highlightedIndex = -1;
        this.isOpen = false;

        this.init();
    }

    init() {
        // Defensive check
        if (!this.trigger) return;

        // Toggle on trigger click
        this.trigger.addEventListener('click', (e) => {
            e.preventDefault();
            this.toggle();
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!this.element.contains(e.target)) {
                this.close();
            }
        });

        // Item selection
        this.items.forEach((item, index) => {
            item.addEventListener('click', () => {
                this.selectItem(item);
            });

            item.addEventListener('mouseenter', () => {
                this.highlightItem(index);
            });
        });

        // Filter input
        if (this.filterInput) {
            this.filterInput.addEventListener('input', () => {
                this.filter(this.filterInput.value);
            });

            this.filterInput.addEventListener('keydown', (e) => {
                this.handleKeydown(e);
            });
        }

        // Keyboard navigation on trigger
        this.trigger.addEventListener('keydown', (e) => {
            this.handleKeydown(e);
        });

        // Set initial selected state
        const selectedItem = this.items.find(item => item.classList.contains('selected'));
        if (selectedItem) {
            this.valueDisplay.textContent = selectedItem.textContent;
            this.valueDisplay.classList.remove('placeholder');
        }
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    open() {
        this.isOpen = true;
        this.element.classList.add('open');
        this.highlightedIndex = -1;

        if (this.filterInput) {
            this.filterInput.value = '';
            this.filter('');
            setTimeout(() => this.filterInput.focus(), 10);
        }

        // Highlight currently selected item
        const selectedIndex = this.items.findIndex(item => item.classList.contains('selected'));
        if (selectedIndex >= 0) {
            this.highlightItem(selectedIndex);
            this.scrollToItem(selectedIndex);
        }
    }

    close() {
        this.isOpen = false;
        this.element.classList.remove('open');
        this.highlightedIndex = -1;
        this.items.forEach(item => item.classList.remove('highlighted'));
    }

    selectItem(item) {
        // Update visual state
        this.items.forEach(i => i.classList.remove('selected'));
        item.classList.add('selected');

        // Update display value
        this.valueDisplay.textContent = item.textContent;
        this.valueDisplay.classList.remove('placeholder');

        // Update hidden input
        if (this.hiddenInput) {
            this.hiddenInput.value = item.dataset.value;
        }

        // Dispatch change event
        const event = new CustomEvent('change', {
            detail: {
                value: item.dataset.value,
                label: item.textContent
            }
        });
        this.element.dispatchEvent(event);

        this.close();
    }

    highlightItem(index) {
        this.items.forEach(item => item.classList.remove('highlighted'));
        if (index >= 0 && index < this.getVisibleItems().length) {
            const visibleItems = this.getVisibleItems();
            visibleItems[index].classList.add('highlighted');
            this.highlightedIndex = index;
        }
    }

    getVisibleItems() {
        return this.items.filter(item => item.style.display !== 'none');
    }

    scrollToItem(index) {
        const visibleItems = this.getVisibleItems();
        if (index >= 0 && index < visibleItems.length) {
            visibleItems[index].scrollIntoView({ block: 'nearest' });
        }
    }

    filter(query) {
        const lowerQuery = query.toLowerCase();
        let hasVisible = false;

        this.items.forEach(item => {
            const text = item.textContent.toLowerCase();
            const matches = text.includes(lowerQuery);
            item.style.display = matches ? '' : 'none';
            if (matches) hasVisible = true;
        });

        // Show/hide empty message
        let emptyMsg = this.panel.querySelector('.xdr-dropdown-empty');
        if (!hasVisible) {
            if (!emptyMsg) {
                emptyMsg = document.createElement('div');
                emptyMsg.className = 'xdr-dropdown-empty';
                emptyMsg.textContent = 'No matches found';
                this.itemsContainer.parentNode.appendChild(emptyMsg);
            }
            emptyMsg.style.display = '';
        } else if (emptyMsg) {
            emptyMsg.style.display = 'none';
        }

        this.highlightedIndex = -1;
    }

    handleKeydown(e) {
        const visibleItems = this.getVisibleItems();

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (!this.isOpen) {
                    this.open();
                } else {
                    const nextIndex = Math.min(this.highlightedIndex + 1, visibleItems.length - 1);
                    this.highlightItem(nextIndex);
                    this.scrollToItem(nextIndex);
                }
                break;

            case 'ArrowUp':
                e.preventDefault();
                if (this.isOpen) {
                    const prevIndex = Math.max(this.highlightedIndex - 1, 0);
                    this.highlightItem(prevIndex);
                    this.scrollToItem(prevIndex);
                }
                break;

            case 'Enter':
                e.preventDefault();
                if (this.isOpen && this.highlightedIndex >= 0) {
                    this.selectItem(visibleItems[this.highlightedIndex]);
                } else if (!this.isOpen) {
                    this.open();
                }
                break;

            case 'Escape':
                e.preventDefault();
                this.close();
                this.trigger.focus();
                break;

            case 'Tab':
                this.close();
                break;
        }
    }

    // Public API
    getValue() {
        return this.hiddenInput ? this.hiddenInput.value : null;
    }

    setValue(value) {
        const item = this.items.find(i => i.dataset.value === value);
        if (item) {
            this.selectItem(item);
        }
    }

    setDisabled(disabled) {
        if (disabled) {
            this.element.classList.add('disabled');
            this.trigger.setAttribute('disabled', '');
        } else {
            this.element.classList.remove('disabled');
            this.trigger.removeAttribute('disabled');
        }
    }
}

// Auto-init: instances manage their own lifecycle via DOM event listeners
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.xdr-dropdown').forEach(el => {
        new XdrDropdown(el);
    });
});

// Export for manual initialization
window.XdrDropdown = XdrDropdown;
