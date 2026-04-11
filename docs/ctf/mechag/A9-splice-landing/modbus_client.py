#!/usr/bin/env python3
"""
Modbus/TCP client helper for OT network enumeration.

Usage:
  modbus_client.py <host> [--port PORT] read <register> [count]
  modbus_client.py <host> [--port PORT] read-input <register> [count]
  modbus_client.py <host> [--port PORT] write <register> <value>
  modbus_client.py <host> [--port PORT] write-coil <coil> <0|1>
  modbus_client.py <host> [--port PORT] devid
  modbus_client.py <host> [--port PORT] scan

Examples:
  modbus_client.py 10.10.40.10 read 0 10
  modbus_client.py 10.10.40.10 write 20 3
  modbus_client.py 10.10.40.10 devid
  modbus_client.py 10.10.40.10 scan
"""

import sys

try:
    from pymodbus.client import ModbusTcpClient
    from pymodbus.pdu.mei_message import ReadDeviceInformationRequest
except ImportError:
    print("Error: pymodbus not installed. Run: pip install pymodbus")
    sys.exit(1)


def read_registers(client, address, count):
    """Read holding registers."""
    result = client.read_holding_registers(address=address, count=count)
    if result.isError():
        print(f"Error reading registers: {result}")
        return
    print(f"Holding registers {address}-{address + count - 1}:")
    for i, val in enumerate(result.registers):
        ascii_char = chr(val) if 32 <= val < 127 else ""
        print(f"  [{address + i:>5d}] = {val:>6d}  (0x{val:04X})  {ascii_char}")


def read_input_registers(client, address, count):
    """Read input registers."""
    result = client.read_input_registers(address=address, count=count)
    if result.isError():
        print(f"Error reading input registers: {result}")
        return
    print(f"Input registers {address}-{address + count - 1}:")
    for i, val in enumerate(result.registers):
        print(f"  [{address + i:>5d}] = {val:>6d}  (0x{val:04X})")


def write_register(client, address, value):
    """Write a single holding register."""
    result = client.write_register(address=address, value=value)
    if result.isError():
        print(f"Error writing register: {result}")
    else:
        print(f"Wrote {value} to holding register {address}")


def write_coil(client, address, value):
    """Write a single coil."""
    result = client.write_coil(address=address, value=bool(value))
    if result.isError():
        print(f"Error writing coil: {result}")
    else:
        print(f"Wrote {'ON' if value else 'OFF'} to coil {address}")


def read_device_id(client):
    """Read device identification (function code 43)."""
    OBJECT_NAMES = {
        0: "VendorName",
        1: "ProductCode",
        2: "MajorMinorRevision",
        3: "VendorUrl",
        4: "ProductName",
        5: "ModelName",
        6: "UserApplicationName",
    }

    for read_code in [1, 2, 3, 4]:  # basic, regular, extended, all
        request = ReadDeviceInformationRequest(read_code=read_code)
        result = client.execute(False, request)
        if hasattr(result, "information") and result.information:
            if read_code == 1:
                print("Device Identification:")
            for obj_id, value in result.information.items():
                name = OBJECT_NAMES.get(obj_id, f"Object_{obj_id}")
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                print(f"  {name}: {value}")


def scan_registers(client):
    """Quick scan of common register ranges."""
    print("=== Quick Register Scan ===")
    ranges = [
        (0, 25, "Operational data"),
        (30, 5, "Mode/control registers"),
        (40, 16, "Extended status"),
        (60, 5, "Dynamic registers"),
        (99, 2, "Challenge registers"),
        (100, 24, "Flag/diagnostic registers"),
        (200, 5, "Response registers"),
    ]
    for start, count, label in ranges:
        result = client.read_holding_registers(address=start, count=count)
        if result.isError():
            continue
        nonzero = [(start + i, v) for i, v in enumerate(result.registers) if v != 0]
        if nonzero:
            print(f"\n  {label} (hr {start}-{start + count - 1}):")
            for addr, val in nonzero:
                ascii_repr = ""
                if 32 <= val < 127:
                    ascii_repr = f"  '{chr(val)}'"
                print(f"    [{addr:>5d}] = {val:>6d}{ascii_repr}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    args = list(sys.argv[1:])
    host = args.pop(0)

    # Optional --port argument
    port = 502
    if args and args[0] == "--port":
        args.pop(0)
        port = int(args.pop(0))

    if not args:
        print(__doc__)
        sys.exit(1)
    command = args.pop(0)

    client = ModbusTcpClient(host, port=port)
    if not client.connect():
        print(f"Failed to connect to {host}:{port}")
        sys.exit(1)

    try:
        if command == "read":
            address = int(args[0]) if len(args) > 0 else 0
            count = int(args[1]) if len(args) > 1 else 1
            read_registers(client, address, count)

        elif command == "read-input":
            address = int(args[0]) if len(args) > 0 else 0
            count = int(args[1]) if len(args) > 1 else 1
            read_input_registers(client, address, count)

        elif command == "write":
            if len(args) < 2:
                print("Usage: write <register> <value>")
                sys.exit(1)
            write_register(client, int(args[0]), int(args[1]))

        elif command == "write-coil":
            if len(args) < 2:
                print("Usage: write-coil <coil> <0|1>")
                sys.exit(1)
            write_coil(client, int(args[0]), int(args[1]))

        elif command == "devid":
            read_device_id(client)

        elif command == "scan":
            scan_registers(client)

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
    finally:
        client.close()


if __name__ == "__main__":
    main()
