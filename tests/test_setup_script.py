"""scripts/setup.py: vscode alt komutu ve .env yardımcıları (ağ/Docker gerektirmez)."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "setup.py"
spec = importlib.util.spec_from_file_location("setup_script", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

URL = "https://models-mcp.corp.example/mcp"


def run_vscode(tmp_path, url=URL):
    setup.main(["vscode", "--url", url, "--dir", str(tmp_path)])
    return json.loads((tmp_path / ".vscode" / "mcp.json").read_text(encoding="utf-8"))


def test_creates_new_mcp_json(tmp_path):
    assert run_vscode(tmp_path) == {"servers": {"models-catalog": {"type": "http", "url": URL}}}


def test_preserves_other_servers_and_keys_and_is_idempotent(tmp_path):
    target = tmp_path / ".vscode" / "mcp.json"
    target.parent.mkdir()
    target.write_text(json.dumps({
        "inputs": [{"id": "x"}],
        "servers": {"other": {"type": "http", "url": "http://other/mcp"},
                    "models-catalog": {"type": "http", "url": "http://old/mcp"}}}), encoding="utf-8")
    first = run_vscode(tmp_path)
    assert first["inputs"] == [{"id": "x"}]
    assert first["servers"]["other"]["url"] == "http://other/mcp"
    assert first["servers"]["models-catalog"]["url"] == URL  # eski adres güncellendi
    assert run_vscode(tmp_path) == first


def test_refuses_to_overwrite_jsonc_with_comments(tmp_path, capsys):
    target = tmp_path / ".vscode" / "mcp.json"
    target.parent.mkdir()
    original = '{\n  // benim yorumum\n  "servers": {}\n}\n'
    target.write_text(original, encoding="utf-8")
    with pytest.raises(SystemExit):
        run_vscode(tmp_path)
    assert target.read_text(encoding="utf-8") == original  # dokunulmadı
    assert "models-catalog" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["localhost:8000/mcp", "ftp://x/mcp", "not a url", ""])
def test_rejects_invalid_urls(tmp_path, bad):
    with pytest.raises(SystemExit):
        run_vscode(tmp_path, bad)
    assert not (tmp_path / ".vscode").exists()


def test_env_helpers(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# yorum\nCATALOG_DATABASE_URL="sqlite:///./x.db"\nOTHER=1\n', encoding="utf-8")
    assert setup.read_env_value(env, "CATALOG_DATABASE_URL") == "sqlite:///./x.db"
    assert setup.read_env_value(env, "MISSING") is None
    assert setup.read_env_value(tmp_path / "yok", "X") is None
    assert setup.redact("postgresql+psycopg://u:sifre@h:5432/d") == "postgresql+psycopg://u:***@h:5432/d"
    assert setup.redact("sqlite:///./dev.db") == "sqlite:///./dev.db"
