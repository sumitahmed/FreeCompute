"""Compatibility entrypoint for the V1 Core-owned image workflow.

Use ``freecompute image`` or ``/connect-image``, ``/image-model``, ``/image``.
Credentials come from dotenv/config; temporary URLs are not saved.
The previous standalone prototype is preserved in Git history.
"""
import sys
from harness.cli.main import main

if __name__ == '__main__':
    sys.argv.insert(1, 'image')
    raise SystemExit(main())
