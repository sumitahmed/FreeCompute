"""Verify public CLI preview assets without connecting to a worker."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

root = Path(__file__).resolve().parents[2]
downloads = root / "site" / "public" / "downloads"
metadata = json.loads((downloads / "provenance.json").read_text(encoding="utf-8"))

for asset in metadata["files"]:
    digest = hashlib.sha256((downloads / asset["name"]).read_bytes()).hexdigest()
    assert digest == asset["sha256"], f"Hash mismatch: {asset['name']}"

notebook_name = "kaggle/freecompute_dual_gpu_server.ipynb"
notebook = (downloads / Path(notebook_name).name).read_bytes()
committed = subprocess.check_output(
    ["git", "show", f"{metadata['commit']}:{notebook_name}"], cwd=root
)
assert notebook == committed, "Notebook download changed from its declared commit"

with zipfile.ZipFile(downloads / "freecompute-v1-source.zip") as archive:
    denied = {".env", "config.yaml", ".git", ".freecompute", ".qwen_harness", "node_modules", "site", "gui"}
    for name in archive.namelist():
        parts = PurePosixPath(name).parts
        assert parts[0] == "FreeCompute-v1-preview", f"Unexpected archive root: {name}"
        assert ".." not in parts and not PurePosixPath(name).is_absolute()
        assert not set(parts) & denied, f"Private/unrelated file in source ZIP: {name}"
        assert PurePosixPath(name).suffix not in {".pyc", ".gguf", ".safetensors", ".exe"}
    assert "FreeCompute-v1-preview/harness/config.sample.yaml" in archive.namelist()
    assert "FreeCompute-v1-preview/pyproject.toml" in archive.namelist()
    assert archive.read(f"FreeCompute-v1-preview/{notebook_name}") == notebook, "ZIP and standalone notebook bytes differ"

data = json.loads(notebook)
for index, cell in enumerate(data["cells"]):
    if cell["cell_type"] == "code":
        assert not cell.get("outputs"), "Notebook contains captured output"
        compile("".join(cell["source"]), f"worker-cell-{index}", "exec")

print("PASS: download hashes, declared source, private-file exclusions, notebook byte identity and static compilation.")
