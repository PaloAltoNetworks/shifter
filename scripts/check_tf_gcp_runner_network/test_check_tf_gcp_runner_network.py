"""Tests for check_tf_gcp_runner_network.py (issue #1546, ADR-008)."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_gcp_runner_network import check_file

# A compliant runner network module: a dedicated custom-mode VPC (never the
# default network) and SSH ingress scoped to Google's IAP relay range only.
GUARDED = """
resource "google_compute_network" "runner" {
  name                    = "shifter-gcp-runner"
  auto_create_subnetworks = false
}

resource "google_compute_firewall" "runner_iap_ssh" {
  name      = "shifter-gcp-runner-iap-ssh"
  network   = google_compute_network.runner.id
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
}

resource "google_compute_firewall" "runner_egress" {
  name               = "shifter-gcp-runner-egress"
  network            = google_compute_network.runner.id
  direction          = "EGRESS"
  destination_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "all"
  }
}
"""

NO_CUSTOM_NETWORK = """
resource "google_compute_firewall" "runner_iap_ssh" {
  network       = "default"
  source_ranges = ["35.235.240.0/20"]
}
"""

AUTO_CREATE_SUBNETWORKS = """
resource "google_compute_network" "runner" {
  name = "shifter-gcp-runner"
}

resource "google_compute_firewall" "runner_iap_ssh" {
  source_ranges = ["35.235.240.0/20"]
}
"""

NO_IAP_RANGE = """
resource "google_compute_network" "runner" {
  auto_create_subnetworks = false
}

resource "google_compute_firewall" "runner_ssh" {
  source_ranges = ["10.0.0.0/8"]
}
"""

WORLD_OPEN_SSH = """
resource "google_compute_network" "runner" {
  auto_create_subnetworks = false
}

resource "google_compute_firewall" "runner_ssh" {
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["35.235.240.0/20", "0.0.0.0/0"]
}
"""


def _write(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".tf", delete=False)
    tmp.write(textwrap.dedent(text))
    tmp.close()
    return Path(tmp.name)


class TestGcpRunnerNetworkGuard(unittest.TestCase):
    def test_compliant_module_has_no_violations(self):
        self.assertEqual(check_file(_write(GUARDED)), [])

    def test_default_network_is_rejected(self):
        violations = check_file(_write(NO_CUSTOM_NETWORK))
        self.assertTrue(violations)

    def test_auto_create_subnetworks_is_rejected(self):
        violations = check_file(_write(AUTO_CREATE_SUBNETWORKS))
        self.assertTrue(any("auto_create_subnetworks" in v.reason for v in violations))

    def test_missing_iap_range_is_rejected(self):
        violations = check_file(_write(NO_IAP_RANGE))
        self.assertTrue(any("IAP" in v.reason or "35.235.240.0/20" in v.reason for v in violations))

    def test_world_open_ingress_is_rejected(self):
        violations = check_file(_write(WORLD_OPEN_SSH))
        self.assertTrue(any("0.0.0.0/0" in v.reason for v in violations))

    def test_deny_all_ingress_default_is_allowed(self):
        # A fail-closed default-deny ingress rule legitimately uses 0.0.0.0/0 in
        # source_ranges with a `deny` clause; it must NOT be flagged as world-open.
        deny_default = GUARDED + textwrap.dedent(
            """
            resource "google_compute_firewall" "runner_deny_ingress_all" {
              name          = "shifter-gcp-runner-deny-ingress-all"
              network       = google_compute_network.runner.id
              direction     = "INGRESS"
              priority      = 65000
              source_ranges = ["0.0.0.0/0"]

              deny {
                protocol = "all"
              }
            }
            """
        )
        self.assertEqual(check_file(_write(deny_default)), [])

    def test_non_tf_file_is_ignored(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        tmp.write("source_ranges = [\"0.0.0.0/0\"]")
        tmp.close()
        self.assertEqual(check_file(Path(tmp.name)), [])


if __name__ == "__main__":
    unittest.main()
