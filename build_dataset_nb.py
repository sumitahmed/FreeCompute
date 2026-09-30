import json
from pathlib import Path

nb = {
    "cells": [],
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.12.13"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 5
}

def add_md(source):
    nb["cells"].append({
        "cell_type": "markdown",
        "metadata": {},
        "source": source.strip()
    })

def add_code(source):
    nb["cells"].append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"trusted": True},
        "outputs": [],
        "source": source.strip()
    })

add_md("""# One-Time Dataset Builder (Create Reusable Kaggle Datasets)

**Purpose:** Run this notebook once to compile `llama-server` and download your model GGUF, saving them as reusable private Kaggle Datasets.
**Benefit:** Eliminates the 6–10 minute compilation/download step. Future server sessions start in **~30 seconds**!

### Kaggle Settings:
- **Accelerator:** `GPU T4 x2` (ensures binary is compiled with CUDA SM 75 for T4)
- **Internet:** `ON`
- **Output:** Saves artifacts into `/kaggle/working/`
""")

add_code("""# Configuration: Choose what to build and download
BUILD_CONFIG = {
    "REPO_ID": "huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF",
    "FILENAME": "Huihui-Qwen3.8-27B-abliterated-UD-DW-Q4_K_M.gguf",
    "REVISION": "3f101cd22b7999228bbd5d79a33975414eb9758b",
    "LLAMA_COMMIT": "2b129ccfa03aea330d2d9ac4650a10de393dbe3a",
}
""")

add_code("""import os, subprocess, shutil
from pathlib import Path

WORK = Path('/kaggle/working')
SCRATCH = Path('/kaggle/tmp/build_dataset')
SCRATCH.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)

# 1. Compile llama-server
SOURCE = SCRATCH / 'llama.cpp'
if not SOURCE.exists():
    subprocess.run(['git', 'clone', 'https://github.com/ggml-org/llama.cpp.git', str(SOURCE)], check=True)
    subprocess.run(['git', '-C', str(SOURCE), 'checkout', BUILD_CONFIG['LLAMA_COMMIT']], check=True)

BUILD = SOURCE / 'build'
subprocess.run([
    'cmake', '-S', str(SOURCE), '-B', str(BUILD),
    '-DGGML_CUDA=ON', '-DGGML_CUDA_NO_VMM=ON',
    '-DCMAKE_CUDA_ARCHITECTURES=75', '-DCMAKE_BUILD_TYPE=Release',
    '-DLLAMA_BUILD_TESTS=OFF',
], check=True)

subprocess.run(['cmake', '--build', str(BUILD), '--target', 'llama-server', '--parallel', '2'], check=True)

compiled_server = BUILD / 'bin' / 'llama-server'
dest_bin = WORK / 'llama-server'
shutil.copy2(compiled_server, dest_bin)
dest_bin.chmod(0o755)
print('Compiled llama-server saved to:', dest_bin)
""")

add_code("""# 2. Download model GGUF
import sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'huggingface_hub>=0.34,<1.0', 'hf_xet>=1.0'], check=True)
from huggingface_hub import hf_hub_download

print('Downloading GGUF to /kaggle/working/... (this will take 1-3 minutes)')
dest_model = hf_hub_download(
    repo_id=BUILD_CONFIG['REPO_ID'],
    filename=BUILD_CONFIG['FILENAME'],
    revision=BUILD_CONFIG['REVISION'],
    local_dir=str(WORK),
)
print('Model saved to:', dest_model)
""")

add_md("""## Next Step: Save as Private Kaggle Dataset
1. Click **Save Version** at the top right of this notebook in Kaggle.
2. Select **Save & Run All (Commit)**.
3. Once the run finishes, navigate to the output tab and click **New Dataset** -> Name it `qwen38-dual-t4-assets`.
4. Now, in your main server notebook (`universal_dual_gpu_server.ipynb`), simply click **+ Add Input** and select your new dataset!
""")

output_path = Path('kaggle/dataset_builder.ipynb')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=2)

print(f'Successfully generated {output_path} with {len(nb["cells"])} cells.')
