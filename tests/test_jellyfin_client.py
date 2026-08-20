"""Test dell'integrazione Jellyfin con httpx mockato: nessuna chiamata di
rete reale viene mai fatta."""
import pytest

from backend.config import settings
from backend.jellyfin import client as jellyfin_client


class _FakeResponse:
    def __init__(self, status_code=204):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.posted_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None):
        self.posted_urls.append((url, headers))
        return _FakeResponse(204)


@pytest.mark.asyncio
async def test_refresh_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "jellyfin_enabled", False)
    result = await jellyfin_client.trigger_library_refresh()
    assert result is False


@pytest.mark.asyncio
async def test_refresh_skipped_when_missing_credentials(monkeypatch):
    monkeypatch.setattr(settings, "jellyfin_enabled", True)
    monkeypatch.setattr(settings, "jellyfin_url", "")
    monkeypatch.setattr(settings, "jellyfin_api_key", "")
    result = await jellyfin_client.trigger_library_refresh()
    assert result is False


@pytest.mark.asyncio
async def test_refresh_success_calls_correct_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "jellyfin_enabled", True)
    monkeypatch.setattr(settings, "jellyfin_url", "http://jellyfin.local:8096")
    monkeypatch.setattr(settings, "jellyfin_api_key", "secret-key")

    fake_client = _FakeAsyncClient()
    monkeypatch.setattr(jellyfin_client.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    result = await jellyfin_client.trigger_library_refresh()

    assert result is True
    assert fake_client.posted_urls[0][0] == "http://jellyfin.local:8096/Library/Refresh"
    assert fake_client.posted_urls[0][1]["X-Emby-Token"] == "secret-key"


@pytest.mark.asyncio
async def test_refresh_failure_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "jellyfin_enabled", True)
    monkeypatch.setattr(settings, "jellyfin_url", "http://jellyfin.local:8096")
    monkeypatch.setattr(settings, "jellyfin_api_key", "secret-key")

    class BrokenClient(_FakeAsyncClient):
        async def post(self, url, headers=None):
            raise ConnectionError("host unreachable")

    monkeypatch.setattr(jellyfin_client.httpx, "AsyncClient", lambda *a, **kw: BrokenClient())

    result = await jellyfin_client.trigger_library_refresh()
    assert result is False  # non deve mai sollevare: un download riuscito non e' un fallimento
