#!/bin/sh
set -eu

if [ -x /generated/run_modbus_server.py ]; then
    exec python /generated/run_modbus_server.py
fi

# Fallback: minimal pymodbus server on the standard port with empty state.
python - <<'PY'
import asyncio
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
from pymodbus.server.async_io import StartAsyncTcpServer

slave = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 100),
    co=ModbusSequentialDataBlock(0, [False] * 100),
    hr=ModbusSequentialDataBlock(0, [0] * 100),
    ir=ModbusSequentialDataBlock(0, [0] * 100),
)
context = ModbusServerContext(slaves=slave, single=True)
asyncio.run(StartAsyncTcpServer(context=context, address=("0.0.0.0", 502)))
PY
