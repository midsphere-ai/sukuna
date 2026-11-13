"""
Build script: obfuscates agent_server/ with PyArmor, compiles tools/ and utils/ to .pyc.

Usage:
    python protect.py --src /path/to/source --out /path/to/output

The source directory must contain agent_server/, tools/, and utils/ subdirectories.
"""

import argparse
import compileall
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL_ENTRY_POINTS = [
    "audio",
    "code",
    "download",
    "file",
    "mobile",
    "plan",
    "read",
    "reasoning",
    "search",
    "slides",
    "vision",
    "web",
]

PYC_TAG = f"cpython-{sys.version_info.major}{sys.version_info.minor}"

STUB_TEMPLATE = """\
import importlib.util, sys, os
_name = {name!r}
_pyc = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "__pycache__", _name + ".{pyc_tag}.pyc")
_spec = importlib.util.spec_from_file_location("__main__", _pyc)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["__main__"] = _mod
_spec.loader.exec_module(_mod)
"""


def obfuscate_agent_server(src: Path, out: Path) -> None:
    """Obfuscate agent_server/ with PyArmor 9."""
    agent_src = src / "agent_server"
    if not agent_src.is_dir():
        print(f"ERROR: {agent_src} not found", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        staging = Path(tmpdir) / "agent_server"
        shutil.copytree(agent_src, staging)

        # Remove pre-existing __pycache__ dirs from staging
        for pycache in list(staging.rglob("__pycache__")):
            shutil.rmtree(pycache)

        # PyArmor preserves the input directory name under -O, so output to `out/`
        # directly — it will create `out/agent_server/` automatically.
        out.mkdir(parents=True, exist_ok=True)

        # Prefer pyarmor from PATH (uv tool install), fall back to python -m pyarmor (pip install)
        pyarmor_bin = shutil.which("pyarmor")
        if pyarmor_bin:
            cmd = [pyarmor_bin, "gen", "-O", str(out), "-r", "-i", str(staging)]
        else:
            cmd = [sys.executable, "-m", "pyarmor", "gen", "-O", str(out), "-r", "-i", str(staging)]
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"PyArmor stdout:\n{result.stdout}", file=sys.stderr)
            print(f"PyArmor stderr:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)

    agent_out = out / "agent_server"
    print(f"  Obfuscated agent_server/ -> {agent_out}")


def compile_directory(src: Path, out: Path, name: str, entry_points: bool = False) -> None:
    """Compile a directory to .pyc, strip .py source, optionally create stubs."""
    src_dir = src / name
    if not src_dir.is_dir():
        print(f"ERROR: {src_dir} not found", file=sys.stderr)
        sys.exit(1)

    dest = out / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_dir, dest)

    # Remove any pre-existing __pycache__ dirs to avoid stale .pyc files
    for pycache in list(dest.rglob("__pycache__")):
        shutil.rmtree(pycache)

    # Compile all .py files to __pycache__/*.{PYC_TAG}.pyc (optimize=0 preserves docstrings)
    success = compileall.compile_dir(str(dest), optimize=0, quiet=1, force=True)
    if not success:
        print(f"ERROR: compileall failed for {name}/", file=sys.stderr)
        sys.exit(1)

    # Collect entry-point names before deleting source
    stub_names = []
    if entry_points:
        for ep in TOOL_ENTRY_POINTS:
            if (dest / f"{ep}.py").exists():
                stub_names.append(ep)

    # Delete all .py source files
    for py_file in dest.rglob("*.py"):
        py_file.unlink()

    # Also handle nested packages (prompts/ etc.)
    for sub_pycache in dest.rglob("__pycache__"):
        parent = sub_pycache.parent
        # For nested packages, delete .py but keep __pycache__
        for py_file in parent.glob("*.py"):
            py_file.unlink()

    # Create thin stubs for entry-point scripts
    if entry_points:
        for ep_name in stub_names:
            stub_path = dest / f"{ep_name}.py"
            stub_path.write_text(STUB_TEMPLATE.format(name=ep_name, pyc_tag=PYC_TAG))

    # Ensure __init__.py stubs exist so the directory is importable as a package
    for init_pyc in dest.rglob(f"__pycache__/__init__.{PYC_TAG}.pyc"):
        init_dir = init_pyc.parent.parent
        init_py = init_dir / "__init__.py"
        if not init_py.exists():
            # Minimal stub — the actual code is in the .pyc
            init_py.write_text("# package init — see __pycache__/\n")

    compiled_count = len(list(dest.rglob("*.pyc")))
    stub_count = len(stub_names)
    print(f"  Compiled {name}/ -> {compiled_count} .pyc files, {stub_count} stubs")


def main() -> None:
    parser = argparse.ArgumentParser(description="Protect source code for E2B sandbox")
    parser.add_argument("--src", required=True, help="Source directory containing agent_server/, tools/, utils/")
    parser.add_argument("--out", required=True, help="Output directory for protected files")
    args = parser.parse_args()

    src = Path(args.src).resolve()
    out = Path(args.out).resolve()

    print(f"Source: {src}")
    print(f"Output: {out}")
    print()

    out.mkdir(parents=True, exist_ok=True)

    print("[1/3] Obfuscating agent_server/ with PyArmor...")
    obfuscate_agent_server(src, out)
    print()

    print("[2/3] Compiling tools/ to bytecode...")
    compile_directory(src, out, "tools", entry_points=True)
    print()

    print("[3/3] Compiling utils/ to bytecode...")
    compile_directory(src, out, "utils", entry_points=False)
    print()

    # Summary
    print("=== Protection Summary ===")
    for dirname in ["agent_server", "tools", "utils"]:
        d = out / dirname
        py_count = len(list(d.rglob("*.py")))
        pyc_count = len(list(d.rglob("*.pyc")))
        print(f"  {dirname}/: {py_count} .py files, {pyc_count} .pyc files")
    print("\nDone.")


if __name__ == "__main__":
    main()
