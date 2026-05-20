/** @odoo-module */

import { PortalHomeCounters } from '@portal/js/portal';

PortalHomeCounters.include({
    /**
     * @override
     * Mostrar la tarjeta de rendiciones siempre, incluso cuando el empleado
     * no tiene rendiciones previas (count = 0).
     */
    _getCountersAlwaysDisplayed() {
        return this._super(...arguments).concat(['expense_count']);
    },
});
