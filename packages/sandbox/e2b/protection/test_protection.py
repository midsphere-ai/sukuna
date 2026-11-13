"""
Verification script for protected E2B sandbox builds.

Run inside the built container:
    python /opt/.midsphere/e2b/protection/test_protection.py
"""

import os
import sys

MIDSPHERE_ROOT = "/opt/.midsphere"
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

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    else:
        passed += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  [{status}] {name}{suffix}")


def test_agent_server_imports() -> None:
    """Test that obfuscated agent_server modules can be imported."""
    print("\n[Test] Agent server imports")
    sys.path.insert(0, MIDSPHERE_ROOT)

    try:
        from agent_server.server import MCPServerConfig  # noqa: F401

        check("import MCPServerConfig", True)
    except Exception as e:
        check("import MCPServerConfig", False, str(e))

    try:
        from agent_server.models import SandboxEvent, SandboxRun  # noqa: F401

        check("import SandboxRun, SandboxEvent", True)
    except Exception as e:
        check("import SandboxRun, SandboxEvent", False, str(e))

    try:
        from agent_server.server import RunNotifyChannel  # noqa: F401

        check("import RunNotifyChannel", True)
    except Exception as e:
        check("import RunNotifyChannel", False, str(e))


def test_pydantic_fields() -> None:
    """Test that Pydantic model fields survived obfuscation."""
    print("\n[Test] Pydantic field preservation")
    try:
        from agent_server.server import MCPServerConfig

        instance = MCPServerConfig(name="test_server", command="echo", args=["hello"])
        dumped = instance.model_dump()
        check("MCPServerConfig.name field", "name" in dumped, f"keys={list(dumped.keys())}")
        check("MCPServerConfig.command field", "command" in dumped)
    except Exception as e:
        check("Pydantic fields", False, str(e))


def test_django_model_fields() -> None:
    """Test that Django model fields survived obfuscation."""
    print("\n[Test] Django model field preservation")
    try:
        from agent_server.models import SandboxRun

        db_table = SandboxRun._meta.db_table
        check(
            "SandboxRun.Meta.db_table",
            db_table == "agent_runs",
            f"db_table={db_table}",
        )
        field_names = [f.name for f in SandboxRun._meta.get_fields()]
        check("SandboxRun has 'id' field", "id" in field_names, f"fields={field_names}")
        check("SandboxRun has 'status' field", "status" in field_names)
    except Exception as e:
        check("Django model fields", False, str(e))


def test_no_source_leakage() -> None:
    """Verify that .py files don't contain real source code."""
    print("\n[Test] Source leakage check")

    agent_dir = os.path.join(MIDSPHERE_ROOT, "agent_server")
    tools_dir = os.path.join(MIDSPHERE_ROOT, "tools")
    utils_dir = os.path.join(MIDSPHERE_ROOT, "utils")

    # agent_server .py files should only contain PyArmor bootstrap
    for root, _dirs, files in os.walk(agent_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath) as f:
                content = f.read()
            # PyArmor files contain __pyarmor__ or are very short bootstraps
            is_pyarmor = "__pyarmor__" in content or "pyarmor" in content.lower()
            is_short = len(content.splitlines()) < 20
            check(
                f"agent_server/{os.path.relpath(fpath, agent_dir)}: no real source",
                is_pyarmor or is_short,
                f"{len(content.splitlines())} lines",
            )

    # tools/ stubs should be very short
    for fname in os.listdir(tools_dir):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(tools_dir, fname)
        with open(fpath) as f:
            lines = f.read().splitlines()
        check(f"tools/{fname}: stub only", len(lines) <= 15, f"{len(lines)} lines")

    # utils/ should have no .py files (only __pycache__/)
    utils_py_files = []
    for root, _dirs, files in os.walk(utils_dir):
        if "__pycache__" in root:
            continue
        for fname in files:
            if fname.endswith(".py"):
                utils_py_files.append(os.path.join(root, fname))

    # Allow minimal __init__.py stubs
    for fpath in utils_py_files:
        with open(fpath) as f:
            lines = f.read().splitlines()
        check(f"utils/{os.path.relpath(fpath, utils_dir)}: minimal stub only", len(lines) <= 5, f"{len(lines)} lines")


def test_tool_stubs_syntax() -> None:
    """Verify that tool stubs are valid Python syntax."""
    print("\n[Test] Tool stub syntax")
    tools_dir = os.path.join(MIDSPHERE_ROOT, "tools")
    for ep in TOOL_ENTRY_POINTS:
        stub = os.path.join(tools_dir, f"{ep}.py")
        if not os.path.exists(stub):
            check(f"tools/{ep}.py exists", False, "file missing")
            continue
        with open(stub) as f:
            source = f.read()
        try:
            compile(source, stub, "exec")
            check(f"tools/{ep}.py syntax", True)
        except SyntaxError as e:
            check(f"tools/{ep}.py syntax", False, str(e))


def test_pyc_files_exist() -> None:
    """Verify .pyc files exist for tools and utils."""
    print("\n[Test] .pyc file presence")
    for dirname in ["tools", "utils"]:
        pycache = os.path.join(MIDSPHERE_ROOT, dirname, "__pycache__")
        has_pycache = os.path.isdir(pycache)
        check(f"{dirname}/__pycache__/ exists", has_pycache)
        if has_pycache:
            pyc_files = [f for f in os.listdir(pycache) if f.endswith(".pyc")]
            check(f"{dirname}/__pycache__/ has .pyc files", len(pyc_files) > 0, f"{len(pyc_files)} files")


def main() -> None:
    print("=" * 60)
    print("E2B Protection Verification")
    print("=" * 60)

    test_agent_server_imports()
    test_pydantic_fields()
    test_django_model_fields()
    test_no_source_leakage()
    test_tool_stubs_syntax()
    test_pyc_files_exist()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
