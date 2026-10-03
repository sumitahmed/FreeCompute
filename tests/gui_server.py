"""Disposable process fixture for browser tests. No production config or GPU."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.api.demo import create_demo
from harness.api.server import APIServer
from harness.security import safe_print


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--info", required=True)
    parser.add_argument("--port", type=int, default=8749)
    args = parser.parse_args()
    info = Path(args.info).resolve()
    if info.parent != Path(tempfile.gettempdir()).resolve() or not info.name.startswith("fc-gui-e2e-"):
        raise ValueError("Fixture auth info must live directly in the OS temporary directory")
    with tempfile.TemporaryDirectory(prefix="fc-gui-browser-") as temp:
        core = create_demo(Path(temp) / "workspace", state_dir=Path(temp) / "state", delay=0.035)
        server = APIServer(core, port=args.port, simulated=True, static_dir=Path(__file__).resolve().parents[1] / "apps/gui/dist").start()
        info.write_text(json.dumps({"url": server.origin, "token": server.token, "workspace": str(core.store.workspace)}), encoding="utf-8")
        info.chmod(0o600)
        safe_print("SIMULATED browser fixture ready:", server.origin)
        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
            info.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
