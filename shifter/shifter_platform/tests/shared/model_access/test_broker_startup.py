"""Standalone startup must not print rejected inventory or secret material."""

import os
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import uvicorn

from model_broker.runtime_server import DrainingServer
from tests.engine.services.test_model_request_accounting import seal_v3_catalog


def test_sigterm_notifies_broker_before_server_exit():
    class Application:
        drained = False

        def begin_drain(self):
            self.drained = True

    app = Application()
    server = DrainingServer(uvicorn.Config(app, lifespan="off"))
    server.handle_exit(signal.SIGTERM, None)
    assert app.drained
    assert server.should_exit


def test_invalid_mounted_inventory_has_a_fixed_startup_error(tmp_path):
    sentinel = "SYNTHETIC-PRIVATE-INVENTORY-2122"
    catalog = seal_v3_catalog(uuid4())
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(catalog.model_dump_json())
    inventory_path = tmp_path / "providers.json"
    inventory_path.write_text('{"private":"' + sentinel + '"}')
    result = subprocess.run(
        [sys.executable, "-m", "model_broker"],
        cwd=Path(__file__).resolve().parents[3],
        env={
            **os.environ,
            "MODEL_BROKER_CATALOG_PATH": str(catalog_path),
            "MODEL_BROKER_CATALOG_DIGEST": catalog.digest,
            "MODEL_BROKER_PROVIDERS_PATH": str(inventory_path),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert sentinel not in result.stdout + result.stderr
    assert result.stderr.strip() == "model broker configuration is invalid"
