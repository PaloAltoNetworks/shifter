/**
 * CTF admin range-list bootstrap tests.
 *
 * The module wires a single DOMContentLoaded handler that reads config from the
 * #ctf-range-list-config element's data-* attributes, constructs the global
 * CTFRangeManager, calls init(), and starts progress polling only when a
 * provisioning run is active.
 */

require('./ctf-range-list.js');

function buildConfig(activeProvisioning) {
    document.body.innerHTML = `
        <div id="ctf-range-list-config"
             data-csrf-token="tok"
             data-provision-all-url="/prov"
             data-range-list-url="/list"
             data-spare-provision-url="/spare"
             data-active-provisioning="${activeProvisioning}"></div>
    `;
}

describe('ctf-range-list bootstrap', () => {
    let instances;

    beforeEach(() => {
        instances = [];
        globalThis.CTFRangeManager = jest.fn(function (opts) {
            this.options = opts;
            this.init = jest.fn();
            this.startProgressPolling = jest.fn();
            instances.push(this);
        });
    });

    test('constructs the manager from config and calls init without polling when inactive', () => {
        buildConfig('false');

        document.dispatchEvent(new Event('DOMContentLoaded'));

        expect(globalThis.CTFRangeManager).toHaveBeenCalledWith({
            csrfToken: 'tok',
            provisionAllUrl: '/prov',
            rangeListUrl: '/list',
            spareProvisionUrl: '/spare',
        });
        expect(instances).toHaveLength(1);
        expect(instances[0].init).toHaveBeenCalledTimes(1);
        expect(instances[0].startProgressPolling).not.toHaveBeenCalled();
    });

    test('starts progress polling when provisioning is active', () => {
        buildConfig('true');

        document.dispatchEvent(new Event('DOMContentLoaded'));

        expect(instances[0].init).toHaveBeenCalledTimes(1);
        expect(instances[0].startProgressPolling).toHaveBeenCalledTimes(1);
    });
});
