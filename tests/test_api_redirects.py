"""Agent credentials and request bodies must never follow HTTP redirects."""

import asyncio

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.bticino_c300x.api import (
    C300XAgentApi,
    C300XAgentApiConnectionError,
)
from custom_components.bticino_c300x.const import HEADER_MAINTENANCE_TOKEN


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("same_origin", [False, True])
@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_agent_redirects_never_forward_credentials_or_payload(status, same_origin, binary, method):
    async def scenario():
        received = []
        origin_headers = []

        async def target(request):
            received.append((dict(request.headers), await request.read()))
            return web.json_response({"ok": True})

        target_app = web.Application()
        target_app.router.add_route("*", "/target", target)
        async with TestServer(target_app) as destination:
            source_app = web.Application()

            async def redirect(request):
                origin_headers.append(dict(request.headers))
                server = source if same_origin else destination
                return web.Response(status=status, headers={"Location": str(server.make_url("/target"))})

            source_app.router.add_route("*", "/redirect", redirect)
            source_app.router.add_route("*", "/target", target)
            async with TestServer(source_app) as source, ClientSession() as session:
                api = C300XAgentApi(session, str(source.make_url("")), "test-bearer", "test-admin")
                with pytest.raises(C300XAgentApiConnectionError, match=f"HTTP {status}") as error:
                    if binary:
                        await api._request_bytes(method, "/redirect", api._maintenance_headers())
                    else:
                        await api._request_json(
                            method, "/redirect", {"value": "private-test-payload"},
                            api._maintenance_headers(),
                        )
                assert "test-admin" not in str(error.value)
                assert "test-bearer" not in str(error.value)
        assert received == []
        assert len(origin_headers) == 1
        assert origin_headers[0]["Authorization"] == "Bearer test-bearer"
        assert origin_headers[0][HEADER_MAINTENANCE_TOKEN] == "test-admin"

    asyncio.run(scenario())
