from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_base_url(url: str) -> str:
    """Duplicate karşılaştırması için URL'yi normalize eder.

    - şema ve host küçük harfe çevrilir (şema yoksa http varsayılır)
    - port her zaman açık yazılır (http→80, https→443 varsayılanları eklenir)
    - sondaki '/' ve sondaki '/v1' atılır, query/fragment silinir
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        port = _DEFAULT_PORTS.get(scheme)

    path = parts.path.rstrip("/")
    if path.lower().endswith("/v1"):
        path = path[: -len("/v1")]
    path = path.rstrip("/")

    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}{path}"


def port_from_url(url: str) -> int | None:
    """URL'de açıkça yazılmış port varsa döner (varsayılan portları saymaz)."""
    raw = (url or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        return urlsplit(raw).port
    except ValueError:
        return None
