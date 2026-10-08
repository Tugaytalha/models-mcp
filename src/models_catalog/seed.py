"""Örnek veri yükler (lokal deneme/demo). Gerçek kayıtlar DEĞİLDİR; host adları uydurmadır.

    CATALOG_DATABASE_URL=sqlite:///./dev.db python -m models_catalog.seed --create-tables

Postgres'e yüklemek için bilinçli olarak --force gerekir (prod verisini kirletmemek için).
"""
from __future__ import annotations

import argparse

from .db.models import Base
from .db.session import get_engine, session_scope
from .services import catalog

SAMPLES: list[dict] = [
    dict(model_name="qwen2.5-32b-instruct", model_id="Qwen/Qwen2.5-32B-Instruct", service_type="llm_chat",
         api_style="openai_compatible", engine="vllm", engine_version="0.6.3", location="atg", environment="dev",
         platform="argocd_k8s", base_url="http://qwen32b.llm-dev.atg.example:8000", port=8000, required_ports=[8000],
         k8s_cluster="atg-dev", k8s_namespace="llm", argocd_app="qwen32b", gpu_type="A100", gpu_count=2,
         max_model_len=32768, supports_tools=True, owner_team="ml-platform", tags=["chat", "tr"],
         description="Genel amaçlı sohbet modeli.", network_notes="ATG dev ağından erişilir."),
    dict(model_name="qwen2.5-32b-instruct", model_id="Qwen/Qwen2.5-32B-Instruct", service_type="llm_chat",
         api_style="openai_compatible", engine="vllm", location="atg", environment="dev", platform="dev_gpu",
         base_url="http://dev-gpu-01.atg.example:8001", port=8001, required_ports=[8001], hostname="dev-gpu-01",
         gpu_type="H100", gpu_count=1, max_model_len=16384, owner_team="ml-platform",
         description="Aynı model, dev-gpu makinesinde (daha kısa context)."),
    dict(model_name="bge-m3", service_type="embedding", api_style="openai_compatible", engine="vllm",
         location="banka", environment="uat", platform="argocd_k8s", base_url="http://bge-m3.uat.banka.example:8000",
         port=8000, required_ports=[8000, 443], k8s_namespace="embeddings", argocd_app="bge-m3", embedding_dim=1024,
         owner_team="ml-platform", access_request_info="Port talebi: Ağ Operasyon formu (örnek)."),
    dict(model_name="bge-reranker-v2-m3", service_type="reranker", api_style="tei", engine="tei",
         location="banka", environment="prod", platform="vm", base_url="http://rerank01.banka.example:8080",
         port=8080, required_ports=[8080], hostname="rerank01", owner_team="ml-platform", status="maintenance"),
    dict(model_name="doc-classifier", service_type="custom", api_style="custom", location="atg", environment="uat",
         platform="docker", base_url="http://svc-docclf.atg.example:9000", port=9000, required_ports=[9000],
         hostname="svc-host-03", endpoint_path="/predict", request_example={"text": "ornek metin", "top_k": 3},
         owner_team="nlp-services", description="Kendi yazdığımız doküman sınıflandırma servisi."),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--create-tables", action="store_true", help="Tabloları oluştur (sadece lokal SQLite için)")
    ap.add_argument("--force", action="store_true", help="SQLite olmayan bir veritabanına yüklemeye izin ver")
    ap.add_argument("--no-samples", action="store_true", help="Örnek veri yükleme (yalnızca --create-tables)")
    args = ap.parse_args()

    engine = get_engine()
    if engine.dialect.name != "sqlite" and not args.force and not args.no_samples:
        raise SystemExit("Örnek veri yalnızca lokal SQLite'a yüklenir. Başka DB için --force kullanın.")
    if args.create_tables:
        Base.metadata.create_all(engine)
    if args.no_samples:
        return

    with session_scope() as s:
        for draft in SAMPLES:
            out = catalog.add(s, draft, actor="seed", source="api", confirm_warnings=True)
            print(f"{out['status']:<10} {draft['model_name']} ({draft['location']}/{draft['environment']}, {draft['platform']})")


if __name__ == "__main__":
    main()
