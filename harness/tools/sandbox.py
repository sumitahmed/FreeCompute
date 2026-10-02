"""Conservative workspace guard: secret variants and all child links are denied."""
import os
import stat
from pathlib import Path

class SandboxSecurityViolation(Exception):
    pass

FORBIDDEN_DIR_NAMES = {".git", ".ssh", ".aws", ".kaggle", ".qwen_harness", ".freecompute"}
FORBIDDEN_EXTENSIONS = {".pem", ".key", ".pfx", ".p12"}
FORBIDDEN_FILENAMES = {".env", ".image_server_url", ".netrc", ".npmrc", ".pypirc", ".git-credentials", "id_rsa", "id_ed25519", "credentials", "secrets.yaml"}

def protected_name(part):
    # Windows treats trailing dots/spaces as aliases; resolved names catch 8.3 aliases.
    name = part.casefold().rstrip(" .")
    return (name in FORBIDDEN_DIR_NAMES or name in FORBIDDEN_FILENAMES
            or name.startswith((".env", "secret", "credential", "id_rsa", "id_ed25519"))
            or Path(name).suffix in FORBIDDEN_EXTENSIONS or ":" in name or "\x00" in name)


def validate_workspace_path(target_path, workspace_root=".", allow_write_to_new_file=False):
    root = Path(workspace_root).resolve()
    candidate = Path(target_path)
    candidate = Path(os.path.abspath(candidate if candidate.is_absolute() else root / candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise SandboxSecurityViolation("Path is outside the approved workspace")
    current = root
    for part in relative.parts:
        if protected_name(part):
            raise SandboxSecurityViolation("Access to protected workspace path denied")
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise SandboxSecurityViolation("Symlink or reparse point access denied")
    resolved = candidate.resolve()
    try:
        resolved_relative = resolved.relative_to(root)
        if any(protected_name(part) for part in resolved_relative.parts):
            raise SandboxSecurityViolation("Resolved path touches protected workspace data")
    except ValueError:
        raise SandboxSecurityViolation("Resolved path is outside workspace")
    return resolved
