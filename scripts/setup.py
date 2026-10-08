#!/usr/bin/env python3
"""Kurulum yardımcısı (yalnızca standart kütüphane; Windows / macOS / Linux).

  python scripts/setup.py local                  # bağımlılıklar + .env + veritabanı (SQLite, örnek veri yok)
  python scripts/setup.py local --seed --run     # örnek veriyi yükle ve sunucuyu başlat
  python scripts/setup.py local --db postgres    # docker compose ile Postgres + migration
  python scripts/setup.py vscode --url https://models-mcp.corp.example/mcp   # .vscode/mcp.json yazar
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "models-catalog"
DB_DEFAULTS = {
    "sqlite": "sqlite:///./dev.db",
    "postgres": "postgresql+psycopg://catalog:catalog@localhost:5432/catalog",
}


def info(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def fail(msg: str) -> NoReturn:
    print(f"HATA: {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    except subprocess.CalledProcessError as e:
        fail(f"Komut başarısız oldu (çıkış kodu {e.returncode}): {' '.join(cmd)}")


# --------------------------------------------------------------------------- .env

def read_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.partition("=")[0].strip() == key:
            return line.partition("=")[2].strip().strip('"').strip("'")
    return None


def ensure_env_file(db: str) -> str:
    """.env yoksa .env.example'dan oluşturur. Etkin DB URL'sini döner (mevcut .env her zaman kazanır)."""
    env_path = ROOT / ".env"
    if env_path.exists():
        url = read_env_value(env_path, "CATALOG_DATABASE_URL") or DB_DEFAULTS[db]
        info(f"Mevcut .env kullanılıyor (DB: {redact(url)}); dokunulmadı.")
        return url
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    lines = [f"CATALOG_DATABASE_URL={DB_DEFAULTS[db]}" if ln.startswith("CATALOG_DATABASE_URL=") else ln
             for ln in text.splitlines()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    info(f".env oluşturuldu (DB: {db}).")
    return DB_DEFAULTS[db]


def redact(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        return url.replace(f":{parts.password}@", ":***@")
    return url


# --------------------------------------------------------------------------- local

def cmd_local(args: argparse.Namespace) -> None:
    if not shutil.which("uv"):
        fail("'uv' bulunamadı. Kurulum: https://docs.astral.sh/uv/  (ör. pip install uv)")

    info("Bağımlılıklar kuruluyor (uv sync, Python 3.12)")
    run(["uv", "sync", "--extra", "dev", "--python", "3.12"])

    db_url = ensure_env_file(args.db)
    env = {**os.environ, "CATALOG_DATABASE_URL": db_url}
    parts = urlsplit(db_url)
    is_sqlite = parts.scheme.startswith("sqlite")
    is_local_pg = not is_sqlite and (parts.hostname or "") in ("localhost", "127.0.0.1", "::1")

    if is_sqlite:
        info("SQLite tabloları oluşturuluyor" + (" ve örnek veri yükleniyor" if args.seed else ""))
        cmd = ["uv", "run", "python", "-m", "models_catalog.seed", "--create-tables"]
        run(cmd + ([] if args.seed else ["--no-samples"]), env)
    else:
        if is_local_pg:
            if not shutil.which("docker"):
                fail("Docker bulunamadı. Docker Desktop'ı kurun ya da '--db sqlite' kullanın.")
            info("Postgres başlatılıyor (docker compose)")
            run(["docker", "compose", "up", "-d", "--wait", "postgres"], env)
        info("Migration çalıştırılıyor (alembic upgrade head; servis de açılışta bunu kendisi yapar)")
        run(["uv", "run", "alembic", "upgrade", "head"], env)
        if args.seed:
            if not is_local_pg:
                fail("Örnek veri yalnızca lokal veritabanına yüklenir (uzak Postgres'e yüklenmez).")
            run(["uv", "run", "python", "-m", "models_catalog.seed", "--force"], env)

    base = f"http://localhost:{args.port}"
    print(f"""
Kurulum tamamlandı.

  Sunucuyu başlat : uv run uvicorn models_catalog.app:app --port {args.port}
  Web kataloğu    : {base}/
  REST API (docs) : {base}/docs
  MCP adresi      : {base}/mcp
  Copilot'a bağla : python scripts/setup.py vscode --url {base}/mcp
  Testler         : uv run pytest
""")
    if args.run:
        info(f"Sunucu başlatılıyor: {base} (durdurmak için Ctrl+C)")
        try:
            run(["uv", "run", "uvicorn", "models_catalog.app:app", "--host", "127.0.0.1",
                 "--port", str(args.port)], env)
        except KeyboardInterrupt:
            pass


# --------------------------------------------------------------------------- vscode

def build_vscode_config(existing: dict | None, url: str) -> dict:
    """Mevcut mcp.json'daki diğer sunucuları korur; yalnızca models-catalog girdisini ekler/günceller."""
    cfg = dict(existing or {})
    servers = dict(cfg.get("servers") or {})
    servers[SERVER_NAME] = {"type": "http", "url": url}
    cfg["servers"] = servers
    return cfg


def cmd_vscode(args: argparse.Namespace) -> None:
    url = args.url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        fail(f"Geçersiz URL: {url!r} (örn. https://models-mcp.corp.example/mcp)")
    if not parts.path.rstrip("/").endswith("/mcp"):
        print(f"UYARI: URL '/mcp' ile bitmiyor ({url}); MCP adresi genellikle .../mcp olur.", file=sys.stderr)

    target = Path(args.dir).resolve() / ".vscode" / "mcp.json"
    existing: dict | None = None
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # VS Code mcp.json'da yorum satırına izin verir; JSON değilse üzerine yazmayız.
            fail(f"{target} geçerli JSON değil (yorum satırı olabilir). Dosyayı bozmamak için dokunulmadı; "
                 f"şu girdiyi elle ekleyin:\n  \"{SERVER_NAME}\": {{ \"type\": \"http\", \"url\": \"{url}\" }}")
        if not isinstance(existing, dict):
            fail(f"{target} beklenen biçimde değil (JSON nesnesi olmalı).")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_vscode_config(existing, url), indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    info(f"{target} güncellendi.")
    print("VS Code'u açın → Copilot Chat → Agent modu → araç listesinde 'models-catalog'u açın.\n"
          "Organizasyonda 'MCP servers in Copilot' politikasının açık olması gerekir.")


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("local", help="Lokal/dev kurulum: bağımlılıklar, .env, veritabanı")
    p.add_argument("--db", choices=list(DB_DEFAULTS), default="sqlite",
                   help=".env yoksa kullanılacak veritabanı (varsayılan: sqlite)")
    p.add_argument("--seed", action="store_true", help="Örnek veriyi yükle (gerçek kayıt değildir)")
    p.add_argument("--run", action="store_true", help="Kurulumdan sonra sunucuyu başlat")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_local)

    p = sub.add_parser("vscode", help="VS Code için .vscode/mcp.json yaz/güncelle")
    p.add_argument("--url", default="http://localhost:8000/mcp", help="MCP adresi (varsayılan: lokal)")
    p.add_argument("--dir", default=".", help="Çalışma alanı klasörü (varsayılan: bulunduğunuz klasör)")
    p.set_defaults(func=cmd_vscode)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
