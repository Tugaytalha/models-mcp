from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CATALOG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://catalog:catalog@localhost:5432/catalog"

    # Açılışta şemayı otomatik günceller (Postgres'te advisory lock ile, çok replica güvenli).
    auto_migrate: bool = True

    # Canlı probe: sunucunun ağ olarak erişebildiği lokasyon/ortamlar (virgülle ayrılmış).
    # Boş bırakılırsa probe kapalı sayılır ve sadece komut üretilir.
    probe_enabled: bool = True
    probe_reachable_locations: str = ""
    probe_reachable_environments: str = ""
    probe_timeout_seconds: float = 5.0

    # DNS-rebinding koruması: kimlik doğrulama olmadığından üretimde sunucunun gerçek host adı
    # yazılmalı (virgülle ayrılmış, örn. "models-mcp.corp.local,models-mcp.corp.local:8000"). "*" = kapalı.
    allowed_hosts: str = "*"

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()] or ["*"]

    @property
    def reachable_locations(self) -> set[str]:
        return {x.strip().lower() for x in self.probe_reachable_locations.split(",") if x.strip()}

    @property
    def reachable_environments(self) -> set[str]:
        return {x.strip().lower() for x in self.probe_reachable_environments.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
