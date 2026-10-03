"""python -m harness.api --demo (never loads real worker credentials)."""
import argparse
from pathlib import Path
import time
import webbrowser

from harness.api.demo import create_demo
from harness.api.server import APIServer
from harness.security import safe_print, scrubber


def main():
    parser = argparse.ArgumentParser(description="FreeCompute authenticated local Core + GUI")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Simulated inference; real tools in an external demo workspace")
    source.add_argument("--config", help="Explicit existing worker YAML configuration (may contact that worker on task submission)")
    parser.add_argument("--workspace", help="Demo workspace; defaults to the persistent OS temp/freecompute-gui-demo directory")
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--origin", action="append", default=[], help="Explicit loopback Vite dev origin, e.g. http://127.0.0.1:5173")
    parser.add_argument("--open", action="store_true", help="Open the built GUI without putting credentials in its URL")
    args = parser.parse_args()
    core, server = None, None
    try:
        if args.demo:
            core = create_demo(args.workspace)
        else:
            if args.workspace:
                raise ValueError("Configure the real workspace in the existing Core YAML; --workspace is demo only")
            from harness.config import HarnessConfig
            from harness.core.service import CoreService
            core = CoreService.from_config(HarnessConfig.load(args.config))
        server = APIServer(core, port=args.port, origins=args.origin, simulated=args.demo,
                           static_dir=Path(__file__).resolve().parents[2] / "apps/gui/dist")
        token_file = core.store.directory / "local-api-token"
        token_file.write_text(server.token, encoding="utf-8")
        token_file.chmod(0o600)
        server.start()
        safe_print("FreeCompute local GUI:", server.origin)
        safe_print("Mode:", "SIMULATED inference; real local approval-gated tools" if args.demo else "configured Core workers")
        safe_print("Local API token file:", token_file)
        safe_print("Paste its value into the GUI's Connect form. Do not use the Kaggle API key.")
        safe_print("Ctrl+C stops this local service. Closing the browser leaves tasks running.")
        if args.open:
            webbrowser.open(server.origin)
        while server.http_thread.is_alive():
            time.sleep(0.25)
    except KeyboardInterrupt:
        safe_print("Stopping the local service; unconfirmed remote outcomes remain quarantined.")
    except Exception as exc:
        safe_print("Local API:", scrubber.scrub(exc))
        return 1
    finally:
        if server and server.http_thread.is_alive():
            server.close()
        elif core:
            core.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
