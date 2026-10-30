import pytest

from app.services.automation_origins import normalize_http_origin, request_origin, validate_origin_fields


def test_origin_matches_whatwg_default_port_ipv6_and_idn():
    assert normalize_http_origin("https://example.test:443") == "https://example.test"
    assert normalize_http_origin("https://example.test:8443") == "https://example.test:8443"
    assert normalize_http_origin("https://[::1]") == "https://[::1]"
    assert normalize_http_origin("https://[0:0:0:0:0:0:0:1]:8443") == "https://[::1]:8443"
    assert normalize_http_origin("https://例子.test") == "https://xn--fsqu00a.test"
    assert normalize_http_origin("https://example.test:443/./") == "https://example.test"
    assert request_origin("https://example.test:443/login") == "https://example.test"


@pytest.mark.parametrize("value", ["https://user:pass@example.test", "https://example.test/app", "javascript:alert(1)", "file:///tmp"])
def test_rejects_non_origins(value):
    with pytest.raises(ValueError):
        normalize_http_origin(value)
    with pytest.raises(ValueError):
        validate_origin_fields({"app_url": value})
