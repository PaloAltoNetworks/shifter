#!/bin/sh
set -eu

# Run the pymodbus server in the background if the scenario seeded one.
if [ -x /generated/run_modbus_server.py ]; then
    python /generated/run_modbus_server.py &
fi

exec python /srv/scada/hmi.py
