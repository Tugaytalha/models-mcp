"""Deployment alan tanımları (tek kaynak).

FIELD_SPECS hem doğrulamada (eksik alan, enum kontrolü), hem `get_field_reference`
çıktısında, hem de kullanıcıya sorulacak soruların üretiminde kullanılır.
Draft alanlarının hepsi Optional'dır: eksik alanlar pydantic hatası değil,
yapılandırılmış "eksik alan" cevabı olarak döner.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .enums import ApiStyle, Environment, Location, Platform, ServiceType, Status


@dataclass(frozen=True)
class FieldSpec:
    name: str
    group: str
    description: str
    question: str
    kind: str = "str"  # str | int | bool | list[str] | list[int] | json
    allowed: list[str] = field(default_factory=list)
    example: str | None = None


FIELD_SPECS: list[FieldSpec] = [
    # Kimlik
    FieldSpec("model_name", "kimlik", "İstekte kullanılan model adı (vLLM served-model-name).",
              "Modelin adı nedir? (isteklerde 'model' alanına yazılan değer)", example="qwen2.5-32b-instruct"),
    FieldSpec("model_id", "kimlik", "Model ID (çoğunlukla model_name ile aynı; boşsa aynı kabul edilir).",
              "Model ID'si model adından farklı mı? Farklıysa yazın.", example="Qwen/Qwen2.5-32B-Instruct"),
    # Sınıf
    FieldSpec("service_type", "sinif", "Servis tipi.", "Bu servis hangi tipte?",
              allowed=ServiceType.values()),
    FieldSpec("api_style", "sinif", "API stili.", "API OpenAI uyumlu mu, TEI mi, yoksa özel bir şema mı?",
              allowed=ApiStyle.values()),
    FieldSpec("engine", "sinif", "Sunucu motoru.", "Hangi motorla çalışıyor? (vllm, tei, triton, custom...)", example="vllm"),
    FieldSpec("engine_version", "sinif", "Motor sürümü.", "Motor sürümü nedir?", example="0.6.3"),
    # Konum
    FieldSpec("location", "konum", "Hangi lokasyonda çalışıyor.", "Banka'da mı ATG'de mi?",
              allowed=Location.values()),
    FieldSpec("environment", "konum", "Ortam.", "Dev, UAT veya Prod'dan hangisi?",
              allowed=Environment.values()),
    FieldSpec("platform", "konum", "Çalıştığı platform.",
              "Hangi platformda? (ArgoCD/k8s, dev-gpu makinesi, VM, docker...)", allowed=Platform.values()),
    # Erişim
    FieldSpec("base_url", "erisim", "Servisin taban adresi (şema + host + port).",
              "Servisin base URL'si nedir? (örn. http://host:8000)", example="http://10.1.2.3:8000"),
    FieldSpec("port", "erisim", "Servisin dinlediği port.", "Servis hangi portta?", kind="int", example="8000"),
    FieldSpec("health_path", "erisim", "Sağlık kontrolü yolu (varsayılan /health).",
              "Sağlık kontrolü yolu farklı mı? (varsayılan /health)", example="/health"),
    FieldSpec("required_ports", "erisim", "Modele erişmek için kullanıcının yetkisi olması gereken portlar.",
              "Erişim için hangi portlara yetki gerekiyor? (virgülle ayırın)", kind="list[int]", example="8000, 443"),
    FieldSpec("network_notes", "erisim", "Hangi network/segmentten erişilir, proxy/NO_PROXY notları.",
              "Hangi network veya segmentten erişilebiliyor? Proxy/NO_PROXY gerekiyor mu?"),
    FieldSpec("access_request_info", "erisim", "Port/firewall izni nasıl talep edilir.",
              "Erişim izni nasıl talep ediliyor? (form linki, ekip, vb.)"),
    # Altyapı
    FieldSpec("hostname", "altyapi", "Servisin ayakta olduğu makine adı.", "Hangi makinede ayakta? (hostname)"),
    FieldSpec("ip", "altyapi", "Makine IP adresi.", "Makinenin IP adresi nedir?"),
    FieldSpec("k8s_cluster", "altyapi", "Kubernetes cluster adı.", "Hangi k8s cluster'ında?"),
    FieldSpec("k8s_namespace", "altyapi", "Kubernetes namespace.", "Hangi namespace'te?"),
    FieldSpec("argocd_app", "altyapi", "ArgoCD uygulama adı.", "ArgoCD uygulama adı nedir?"),
    FieldSpec("gpu_type", "altyapi", "GPU tipi.", "Hangi GPU üzerinde? (A100, H100, L40S...)"),
    FieldSpec("gpu_count", "altyapi", "GPU adedi.", "Kaç GPU kullanıyor?", kind="int"),
    # Model parametreleri
    FieldSpec("max_model_len", "model", "Context length (max_model_len).", "Context length (max_model_len) kaç?", kind="int", example="32768"),
    FieldSpec("embedding_dim", "model", "Embedding vektör boyutu.", "Embedding boyutu kaç?", kind="int", example="1024"),
    FieldSpec("max_input_tokens", "model", "Girdi için azami token.", "Azami girdi token sayısı kaç?", kind="int"),
    FieldSpec("quantization", "model", "Quantization.", "Quantization var mı? (awq, gptq, fp8...)"),
    FieldSpec("dtype", "model", "Veri tipi.", "dtype nedir? (bfloat16, float16...)"),
    FieldSpec("hf_model_path", "model", "HuggingFace veya disk üzerindeki model yolu.", "Model yolu/HF adı nedir?"),
    FieldSpec("supports_tools", "model", "Tool/function calling desteği.", "Tool calling destekliyor mu?", kind="bool"),
    FieldSpec("supports_reasoning", "model", "Reasoning desteği.", "Reasoning (düşünme) destekliyor mu?", kind="bool"),
    FieldSpec("supports_vision", "model", "Görüntü girdisi desteği.", "Görüntü girdisi destekliyor mu?", kind="bool"),
    # Custom servis
    FieldSpec("endpoint_path", "custom", "Özel servisin istek yolu.", "İstek atılan endpoint yolu nedir? (örn. /predict)", example="/predict"),
    FieldSpec("request_example", "custom", "Örnek istek gövdesi (JSON).", "Örnek bir istek gövdesi (JSON) verir misiniz?", kind="json"),
    FieldSpec("response_example", "custom", "Örnek cevap gövdesi (JSON).", "Örnek bir cevap (JSON) verir misiniz?", kind="json"),
    FieldSpec("openapi_url", "custom", "OpenAPI/Swagger adresi.", "OpenAPI/Swagger adresi var mı?"),
    # Meta
    FieldSpec("description", "meta", "Kısa açıklama / kullanım önerisi.", "Model/servis için kısa bir açıklama yazar mısınız?"),
    FieldSpec("tags", "meta", "Etiketler.", "Etiket eklemek ister misiniz? (virgülle ayırın)", kind="list[str]"),
    FieldSpec("owner_team", "meta", "Sahip ekip.", "Servisin sahibi hangi ekip?"),
    FieldSpec("owner_contact", "meta", "İletişim (kişi/kanal).", "İletişim için kişi veya kanal nedir?"),
    FieldSpec("status", "meta", "Durum (varsayılan active).", "Durumu nedir?", allowed=Status.values()),
]

FIELD_BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELD_SPECS}
DRAFT_FIELDS: set[str] = set(FIELD_BY_NAME)


class DeploymentDraft(BaseModel):
    """Eklenecek/güncellenecek kayıt. Tüm alanlar opsiyonel; eksikleri validation bulur."""

    model_config = ConfigDict(extra="forbid")

    model_name: str | None = None
    model_id: str | None = None
    service_type: str | None = None
    api_style: str | None = None
    engine: str | None = None
    engine_version: str | None = None
    location: str | None = None
    environment: str | None = None
    platform: str | None = None
    base_url: str | None = None
    port: int | None = None
    health_path: str | None = None
    required_ports: list[int] | None = None
    network_notes: str | None = None
    access_request_info: str | None = None
    hostname: str | None = None
    ip: str | None = None
    k8s_cluster: str | None = None
    k8s_namespace: str | None = None
    argocd_app: str | None = None
    gpu_type: str | None = None
    gpu_count: int | None = None
    max_model_len: int | None = None
    embedding_dim: int | None = None
    max_input_tokens: int | None = None
    quantization: str | None = None
    dtype: str | None = None
    hf_model_path: str | None = None
    supports_tools: bool | None = None
    supports_reasoning: bool | None = None
    supports_vision: bool | None = None
    endpoint_path: str | None = None
    request_example: dict[str, Any] | None = None
    response_example: dict[str, Any] | None = None
    openapi_url: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    owner_team: str | None = None
    owner_contact: str | None = None
    status: str | None = None

    def provided(self) -> dict[str, Any]:
        """Boş string/None olmayan alanlar."""
        out: dict[str, Any] = {}
        for k, v in self.model_dump().items():
            if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
                continue
            out[k] = v.strip() if isinstance(v, str) else v
        return out


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_name: str
    model_id: str
    service_type: str
    api_style: str
    engine: str | None
    engine_version: str | None
    location: str
    environment: str
    platform: str
    base_url: str
    port: int
    health_path: str
    required_ports: list[int]
    network_notes: str | None
    access_request_info: str | None
    hostname: str | None
    ip: str | None
    k8s_cluster: str | None
    k8s_namespace: str | None
    argocd_app: str | None
    gpu_type: str | None
    gpu_count: int | None
    max_model_len: int | None
    embedding_dim: int | None
    max_input_tokens: int | None
    quantization: str | None
    dtype: str | None
    hf_model_path: str | None
    supports_tools: bool | None
    supports_reasoning: bool | None
    supports_vision: bool | None
    endpoint_path: str | None
    request_example: dict[str, Any] | None
    response_example: dict[str, Any] | None
    openapi_url: str | None
    description: str | None
    tags: list[str]
    owner_team: str | None
    owner_contact: str | None
    status: str
    last_health_status: str | None
    last_health_at: datetime | None
    last_health_detail: str | None
    created_by: str
    created_at: datetime
    updated_by: str | None
    updated_at: datetime | None
    deleted_by: str | None
    deleted_at: datetime | None
    delete_reason: str | None
