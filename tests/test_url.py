import pytest

from models_catalog.domain.url import normalize_base_url, port_from_url


@pytest.mark.parametrize("raw, expected", [
    ("http://Host:8000/", "http://host:8000"),
    ("http://host:8000/v1", "http://host:8000"),
    ("http://host:8000/v1/", "http://host:8000"),
    ("HTTP://HOST:8000/V1", "http://host:8000"),
    ("host:8000", "http://host:8000"),
    ("http://host", "http://host:80"),
    ("https://host", "https://host:443"),
    ("https://host/models/v1", "https://host:443/models"),
    ("http://host:8000/?a=1#x", "http://host:8000"),
    ("  http://host:8000  ", "http://host:8000"),
    ("", ""),
])
def test_normalize(raw, expected):
    assert normalize_base_url(raw) == expected


def test_port_from_url():
    assert port_from_url("http://host:8123/v1") == 8123
    assert port_from_url("http://host") is None
    assert port_from_url("host:9000") == 9000
