#!/usr/bin/env python3
"""Test script for pan-os-python API with standalone NGFW.

Test NGFW: i-06aea0874efad8846
Public IP: 18.219.16.160
Private IP: 172.31.39.134

Bootstrap configured with SCM auto-registration, should license itself.
"""

import time
import sys


def test_api_connection(host):
    """Test basic API connectivity."""
    print(f"\n=== Testing API Connection to {host} ===")

    try:
        from panos import firewall
    except ImportError:
        print("ERROR: pan-os-python not installed")
        print("Install with: pip install pan-os-python")
        return False

    try:
        print("Connecting to PAN-OS API...")
        fw = firewall.Firewall(host, api_username="admin", api_password="admin")

        print("Running: show system info")
        result = fw.op("show system info")

        print("\n✓ API connection successful!")
        return fw, result

    except Exception as e:
        print(f"\n✗ API connection failed: {e}")
        return None, None


def parse_system_info(result_xml):
    """Parse system info from XML response."""
    print("\n=== Parsing System Info ===")

    try:
        import xml.etree.ElementTree as ET

        # Find the <system> element
        system = result_xml.find(".//system")
        if system is None:
            print("ERROR: <system> element not found in XML")
            return None

        # Extract key fields
        info = {}
        for child in system:
            info[child.tag] = child.text or ""

        # Display key fields
        print(f"Hostname: {info.get('hostname', 'unknown')}")
        print(f"Serial: {info.get('serial', 'unknown')}")
        print(f"Model: {info.get('model', 'unknown')}")
        print(f"SW Version: {info.get('sw-version', 'unknown')}")
        print(f"VM License: {info.get('vm-license', 'none')}")
        print(f"Device Cert Status: {info.get('device-certificate-status', 'None')}")
        print(f"IP Address: {info.get('ip-address', 'unknown')}")

        return info

    except Exception as e:
        print(f"ERROR parsing XML: {e}")
        return None


def test_configuration(fw):
    """Test configuration operations via API."""
    print("\n=== Testing Configuration Operations ===")

    try:
        from panos.objects import AddressObject

        # Create test address object
        print("Creating address object 'test-subnet'...")
        addr = AddressObject(
            name="test-subnet",
            value="10.99.99.0/24",
            description="Test address created via pan-os-python"
        )
        fw.add(addr)
        addr.create()

        print("Committing configuration...")
        fw.commit()

        print("\n✓ Configuration test successful!")

        # Clean up
        print("Cleaning up test object...")
        addr.delete()
        fw.commit()

        return True

    except Exception as e:
        print(f"\n✗ Configuration test failed: {e}")
        return False


def main():
    host = "18.219.16.160"

    print("=" * 70)
    print("PAN-OS API Test Script")
    print("=" * 70)
    print("\nNOTE: VM-Series takes 15-20 minutes to fully boot.")
    print("If connection fails, wait and retry.")
    print("\nPress Ctrl+C to exit")
    print("=" * 70)

    # Test connection with retries
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        print(f"\n[Attempt {attempt}/{max_retries}]")

        fw, result = test_api_connection(host)
        if fw and result:
            # Parse and display system info
            info = parse_system_info(result)

            if info:
                # Check if serial is available
                serial = info.get('serial', '').lower()
                if serial and serial not in ('unknown', 'none', ''):
                    print("\n✓ Serial number available - bootstrap complete!")

                    # Test configuration if desired
                    if '--config' in sys.argv:
                        test_configuration(fw)
                else:
                    print("\n⚠ Serial still 'unknown' - bootstrap in progress...")

            print("\n=== Test Complete ===")
            break
        else:
            if attempt < max_retries:
                print(f"Waiting 30 seconds before retry...")
                time.sleep(30)
            else:
                print("\n✗ All connection attempts failed")
                print("NGFW may not be fully booted yet. Wait 10-15 minutes and try again.")
                return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
