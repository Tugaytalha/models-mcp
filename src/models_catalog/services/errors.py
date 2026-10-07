class CatalogError(Exception):
    """Kullanıcıya gösterilebilir iş kuralı hatası."""


class NotFound(CatalogError):
    pass
