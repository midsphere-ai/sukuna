"""Unit tests for sandbox file system path traversal prevention.

Tests cover:
- ../../../etc/passwd traversal
- ....// double-dot variants
- Null byte injection
- Symlink escape
- URL-encoded traversal (%2e%2e%2f)
- Sensitive path blocking (/etc/shadow, /proc, .env, .ssh/)
- Valid paths still work
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from ninja.errors import HttpError as HTTPException


# We need to patch config values before importing the function under test.
# The server module reads SANDBOX_WORKSPACE_ROOT at import time.
@pytest.fixture(autouse=True)
def sandbox_root(tmp_path: Path):
    """Create a temporary sandbox root and patch _FILES_ROOT."""
    # Create some files inside the sandbox for valid-path tests
    (tmp_path / "hello.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file.py").write_text("print('hi')")

    import agent_server.api.files as files_mod

    original = files_mod._FILES_ROOT
    files_mod._FILES_ROOT = tmp_path
    yield tmp_path
    files_mod._FILES_ROOT = original


def _resolve(path: str, *, must_exist: bool = True):
    from agent_server.server import _resolve_sandbox_path

    return _resolve_sandbox_path(path, must_exist=must_exist)


# ── Traversal attacks ────────────────────────────────────────────────────────


class TestDirectoryTraversal:
    def test_classic_dotdot_etc_passwd(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("../../../etc/passwd")
        assert exc_info.value.status_code == 403

    def test_dotdot_single(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("..")
        assert exc_info.value.status_code == 403

    def test_dotdot_in_middle(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("subdir/../../etc/passwd")
        assert exc_info.value.status_code == 403

    def test_quadruple_dot_slash(self, sandbox_root):
        """....// variant — should still be caught."""
        with pytest.raises(HTTPException) as exc_info:
            _resolve("....//etc/passwd")
        assert exc_info.value.status_code == 403

    def test_dotdot_backslash(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("..\\..\\etc\\passwd")
        assert exc_info.value.status_code == 403


# ── Null byte injection ─────────────────────────────────────────────────────


class TestNullByteInjection:
    def test_null_byte_in_path(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("hello.txt\x00.jpg")
        assert exc_info.value.status_code == 403
        assert "null bytes" in exc_info.value.detail

    def test_null_byte_at_start(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("\x00/etc/passwd")
        assert exc_info.value.status_code == 403


# ── URL-encoded traversal ───────────────────────────────────────────────────


class TestURLEncodedTraversal:
    def test_percent_encoded_dotdot(self, sandbox_root):
        """``%2e%2e%2f`` should be decoded and caught."""
        with pytest.raises(HTTPException) as exc_info:
            _resolve("%2e%2e%2f%2e%2e%2fetc/passwd")
        assert exc_info.value.status_code == 403

    def test_mixed_encoding(self, sandbox_root):
        """``..%2f`` mixed traversal."""
        with pytest.raises(HTTPException) as exc_info:
            _resolve("..%2f..%2fetc/passwd")
        assert exc_info.value.status_code == 403

    def test_double_encoded_null(self, sandbox_root):
        """``%00`` null byte via URL encoding."""
        with pytest.raises(HTTPException) as exc_info:
            _resolve("hello%00.txt")
        assert exc_info.value.status_code == 403


# ── Symlink escape ───────────────────────────────────────────────────────────


class TestSymlinkEscape:
    def test_symlink_pointing_outside(self, sandbox_root):
        """A symlink inside the sandbox pointing to /tmp should be blocked."""
        outside_dir = tempfile.mkdtemp()
        secret = Path(outside_dir) / "secret.txt"
        secret.write_text("top-secret")

        link = sandbox_root / "evil_link"
        link.symlink_to(outside_dir)

        with pytest.raises(HTTPException) as exc_info:
            _resolve("evil_link")
        assert exc_info.value.status_code == 403
        assert "symlink" in exc_info.value.detail or "outside" in exc_info.value.detail

        # Clean up
        os.unlink(link)
        secret.unlink()
        os.rmdir(outside_dir)

    def test_symlink_inside_sandbox_allowed(self, sandbox_root):
        """A symlink that stays inside the sandbox should be allowed."""
        target = sandbox_root / "hello.txt"
        link = sandbox_root / "good_link"
        link.symlink_to(target)

        result = _resolve("good_link")
        assert result == target.resolve()

        os.unlink(link)


# ── Sensitive path blocking ──────────────────────────────────────────────────


class TestSensitivePaths:
    def test_etc_shadow(self, sandbox_root):
        """Even if sandbox root were /, /etc/shadow must be blocked."""
        import agent_server.api.files as files_mod

        original = files_mod._FILES_ROOT
        files_mod._FILES_ROOT = Path("/")
        try:
            with pytest.raises(HTTPException) as exc_info:
                _resolve("etc/shadow")
            assert exc_info.value.status_code == 403
            assert "sensitive" in exc_info.value.detail
        finally:
            files_mod._FILES_ROOT = original

    def test_proc_access(self, sandbox_root):
        """Access to /proc should be blocked."""
        import agent_server.api.files as files_mod

        original = files_mod._FILES_ROOT
        files_mod._FILES_ROOT = Path("/")
        try:
            with pytest.raises(HTTPException) as exc_info:
                _resolve("proc/self/environ")
            assert exc_info.value.status_code == 403
        finally:
            files_mod._FILES_ROOT = original

    def test_dotenv_file(self, sandbox_root):
        """Access to .env files should be blocked."""
        env_file = sandbox_root / ".env"
        env_file.write_text("SECRET=foo")

        with pytest.raises(HTTPException) as exc_info:
            _resolve(".env")
        assert exc_info.value.status_code == 403
        assert "sensitive" in exc_info.value.detail

    def test_ssh_directory(self, sandbox_root):
        """Access to .ssh directory should be blocked."""
        ssh_dir = sandbox_root / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("private-key")

        with pytest.raises(HTTPException) as exc_info:
            _resolve(".ssh")
        assert exc_info.value.status_code == 403

    def test_vault_token(self, sandbox_root):
        """Access to .vault-token should be blocked."""
        vault = sandbox_root / ".vault-token"
        vault.write_text("s.token123")

        with pytest.raises(HTTPException) as exc_info:
            _resolve(".vault-token")
        assert exc_info.value.status_code == 403


# ── Valid paths ──────────────────────────────────────────────────────────────


class TestValidPaths:
    def test_empty_path_returns_root(self, sandbox_root):
        result = _resolve("")
        assert result == sandbox_root

    def test_simple_file(self, sandbox_root):
        result = _resolve("hello.txt")
        assert result == sandbox_root / "hello.txt"

    def test_nested_file(self, sandbox_root):
        result = _resolve("subdir/file.py")
        assert result == sandbox_root / "subdir" / "file.py"

    def test_must_exist_false_for_new_file(self, sandbox_root):
        result = _resolve("new_file.txt", must_exist=False)
        assert result == (sandbox_root / "new_file.txt").resolve()

    def test_nonexistent_raises_404(self, sandbox_root):
        with pytest.raises(HTTPException) as exc_info:
            _resolve("does_not_exist.txt")
        assert exc_info.value.status_code == 404
