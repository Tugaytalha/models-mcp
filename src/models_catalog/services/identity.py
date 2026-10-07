"""İşlemi yapan kişi (actor). Şimdilik doğrulanmaz; kullanıcının verdiği isim alınır.

Kimlik doğrulama (kişisel token / Entra ID) eklenecekse yalnızca bu fonksiyon değişir.
"""
from __future__ import annotations

from .errors import CatalogError


def get_actor(performed_by: str | None) -> str:
    actor = (performed_by or "").strip()
    if not actor:
        raise CatalogError("'performed_by' (işlemi yapan kişinin adı) zorunludur. Kullanıcıya adını sorun.")
    return actor[:128]
