#!/usr/bin/env python3
"""UAT test script - writes a marker file and prints output."""
import datetime
import os

output_dir = "/tmp"
marker = os.path.join(output_dir, "uat_marker.txt")

with open(marker, "w") as f:
    f.write(f"UAT test executed at {datetime.datetime.now().isoformat()}\n")

print("UAT test script executed successfully")
print(f"Marker file written to {marker}")
