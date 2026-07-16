"""Unit tests for the one-command local startup launcher."""

from __future__ import annotations

import importlib.util
from pathlib import Path

START_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start.py"


def load_start_module():
    spec = importlib.util.spec_from_file_location("pfis_start_launcher", START_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def patch_env_paths(monkeypatch, module, tmp_path):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "BACKEND_DIR", backend_dir)
    monkeypatch.setattr(module, "ENV_FILE", backend_dir / ".env")
    monkeypatch.setattr(module, "ENV_EXAMPLE", backend_dir / ".env.example")
    monkeypatch.setattr(module, "ROOT_ENV_FILE", tmp_path / ".env")
    return backend_dir


def test_ensure_env_file_creates_generated_secret_from_example(monkeypatch, tmp_path):
    module = load_start_module()
    backend_dir = patch_env_paths(monkeypatch, module, tmp_path)
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda _: "generated-local-secret")
    module.ENV_EXAMPLE.write_text(
        "DATABASE_URL=sqlite+aiosqlite:///./pfis.db\n"
        f"SECRET_KEY={module.EXAMPLE_SECRET_KEY}\n"
        "AUTH_REQUIRED=true\n",
        encoding="utf-8",
    )

    module.ensure_env_file()

    env_text = (backend_dir / ".env").read_text(encoding="utf-8")
    assert "SECRET_KEY=generated-local-secret" in env_text
    assert module.EXAMPLE_SECRET_KEY not in env_text


def test_ensure_env_file_rotates_root_env_placeholder(monkeypatch, tmp_path):
    module = load_start_module()
    patch_env_paths(monkeypatch, module, tmp_path)
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda _: "root-generated-secret")
    module.ENV_FILE.write_text("SECRET_KEY=already-safe\n", encoding="utf-8")
    module.ROOT_ENV_FILE.write_text(
        f"SECRET_KEY={module.EXAMPLE_SECRET_KEY}\nDEBUG=true\n",
        encoding="utf-8",
    )

    module.ensure_env_file()

    root_env_text = module.ROOT_ENV_FILE.read_text(encoding="utf-8")
    assert "SECRET_KEY=root-generated-secret" in root_env_text
    assert module.EXAMPLE_SECRET_KEY not in root_env_text


def test_ensure_env_file_preserves_existing_custom_secret(monkeypatch, tmp_path):
    module = load_start_module()
    patch_env_paths(monkeypatch, module, tmp_path)
    module.ENV_FILE.write_text("SECRET_KEY=custom-local-secret\n", encoding="utf-8")
    module.ROOT_ENV_FILE.write_text("SECRET_KEY=custom-root-secret\n", encoding="utf-8")

    module.ensure_env_file()

    assert module.ENV_FILE.read_text(encoding="utf-8") == "SECRET_KEY=custom-local-secret\n"
    assert module.ROOT_ENV_FILE.read_text(encoding="utf-8") == "SECRET_KEY=custom-root-secret\n"


def test_rotate_placeholder_secret_handles_default_development_secret(monkeypatch, tmp_path):
    module = load_start_module()
    patch_env_paths(monkeypatch, module, tmp_path)
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda _: "rotated-default-secret")
    module.ENV_FILE.write_text(f"SECRET_KEY={module.DEFAULT_SECRET_KEY}\n", encoding="utf-8")

    module.ensure_env_file()

    assert module.ENV_FILE.read_text(encoding="utf-8") == "SECRET_KEY=rotated-default-secret\n"


def test_check_port_returns_requested_port_when_free():
    import socket

    module = load_start_module()
    # Grab any free ephemeral port from the OS, then release it and ask check_port for it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert module.check_port("127.0.0.1", free_port) == free_port


def test_check_port_advances_when_occupied():
    import socket

    module = load_start_module()
    # Hold a port without SO_REUSEADDR to ensure _is_port_free sees it as occupied
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        occupied_port = s.getsockname()[1]
        result = module.check_port("127.0.0.1", occupied_port)
    assert result != occupied_port
    assert isinstance(result, int)


def test_find_free_port_returns_none_when_all_taken(monkeypatch):
    module = load_start_module()
    monkeypatch.setattr(module, "_is_port_free", lambda host, port: False)
    result = module._find_free_port("127.0.0.1", 9000, attempts=5)
    assert result is None
