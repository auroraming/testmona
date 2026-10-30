import pytest

from app.services.playwright_mcp_transport import PLAYWRIGHT_SAFE_TOOLS, build_playwright_mcp_transport


def test_builds_isolated_pinned_transport(tmp_path):
    transport = build_playwright_mcp_transport(package_ref="@playwright/mcp@1.2.3", allowed_origin="https://example.test:8443", workspace=tmp_path)
    assert transport.command == "npx"
    assert transport.cwd == str(tmp_path.resolve())
    assert "--headless" in transport.args
    assert "--isolated" in transport.args
    assert "--allowed-origins=https://example.test:8443" in transport.args
    assert {"browser_run_code_unsafe", "browser_evaluate", "browser_file_upload"}.isdisjoint(PLAYWRIGHT_SAFE_TOOLS)


@pytest.mark.parametrize("package_ref", ["@playwright/mcp@latest", "@playwright/mcp", "other@1.2.3"])
def test_rejects_unpinned_or_unexpected_package(package_ref, tmp_path):
    with pytest.raises(ValueError, match="pin an exact"):
        build_playwright_mcp_transport(package_ref=package_ref, allowed_origin="https://example.test", workspace=tmp_path)


@pytest.mark.parametrize("origin", ["file:///tmp", "https://user:pass@example.test", "https://example.test/path", "javascript:alert(1)"])
def test_rejects_unsafe_origin(origin, tmp_path):
    with pytest.raises(ValueError):
        build_playwright_mcp_transport(package_ref="@playwright/mcp@1.2.3", allowed_origin=origin, workspace=tmp_path)
