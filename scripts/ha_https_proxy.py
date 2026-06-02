#!/usr/bin/env python3
"""Local HTTPS reverse proxy for Home Assistant frontend microphone tests."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import ssl
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from aiohttp import ClientConnectionResetError, ClientSession, WSMsgType, web

DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 8443
DEFAULT_CERT_DIR = Path.home() / ".cache" / "bticino-c300x-ha-https-proxy"
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def parse_args() -> argparse.Namespace:
    """Return command-line options."""

    parser = argparse.ArgumentParser(
        description=(
            "Expose an existing Home Assistant URL through a local HTTPS proxy. "
            "Useful for WebRTC microphone/talkback tests."
        )
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("HA_TEST_URL", ""),
        help="Home Assistant base URL. Defaults to HA_TEST_URL.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_LISTEN_HOST,
        help=f"Listen host. Defaults to {DEFAULT_LISTEN_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_LISTEN_PORT,
        help=f"Listen port. Defaults to {DEFAULT_LISTEN_PORT}.",
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=DEFAULT_CERT_DIR,
        help=f"Directory for the generated localhost certificate. Defaults to {DEFAULT_CERT_DIR}.",
    )
    parser.add_argument(
        "--forwarded-headers",
        action="store_true",
        help=(
            "Send X-Forwarded-* headers. Leave disabled unless Home Assistant "
            "trusts this proxy."
        ),
    )
    return parser.parse_args()


def target_base_url(raw_target: str) -> str:
    """Validate and normalize the upstream Home Assistant URL."""

    target = raw_target.strip().rstrip("/")
    parsed = urlsplit(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("Set HA_TEST_URL or pass --target with a valid HA URL.")
    return target


def ensure_localhost_certificate(cert_dir: Path) -> tuple[Path, Path]:
    """Create a local self-signed SAN certificate if needed."""

    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "localhost.crt"
    key_path = cert_dir / "localhost.key"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    config_path = cert_dir / "localhost.openssl.cnf"
    config_path.write_text(
        """[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[dn]
CN = localhost

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "30",
            "-config",
            str(config_path),
            "-sha256",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    key_path.chmod(0o600)
    return cert_path, key_path


def proxy_headers(
    request: web.Request,
    target: str,
    *,
    forwarded_headers: bool,
) -> dict[str, str]:
    """Return request headers safe to forward to Home Assistant."""

    target_host = urlsplit(target).netloc
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_HEADERS and key.lower() != "host"
    }
    headers["Host"] = target_host
    if forwarded_headers:
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-Host"] = request.host
        headers["X-Forwarded-For"] = request.remote or "127.0.0.1"
    return headers


def response_headers(headers: object) -> dict[str, str]:
    """Return upstream response headers safe to send to the browser."""

    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_HEADERS
    }


def upstream_url(target: str, request: web.Request) -> str:
    """Build upstream URL for a proxied request."""

    path_qs = request.rel_url.raw_path_qs
    return urljoin(f"{target}/", path_qs.lstrip("/"))


async def proxy_websocket(
    request: web.Request,
    session: ClientSession,
    target: str,
    forwarded_headers: bool,
) -> web.WebSocketResponse:
    """Proxy Home Assistant websocket traffic in both directions."""

    ws_response = web.WebSocketResponse()
    await ws_response.prepare(request)

    url = upstream_url(target, request).replace("https://", "wss://", 1).replace(
        "http://",
        "ws://",
        1,
    )
    async with session.ws_connect(
        url,
        headers=proxy_headers(
            request,
            target,
            forwarded_headers=forwarded_headers,
        ),
        heartbeat=30,
        max_msg_size=0,
    ) as upstream:
        async def client_to_upstream() -> None:
            async for message in ws_response:
                if message.type == WSMsgType.TEXT:
                    await upstream.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await upstream.send_bytes(message.data)
                elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
                    await upstream.close()

        async def upstream_to_client() -> None:
            async for message in upstream:
                if message.type == WSMsgType.TEXT:
                    await ws_response.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await ws_response.send_bytes(message.data)
                elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}:
                    await ws_response.close()

        tasks = [
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(asyncio.CancelledError):
                task.result()
    return ws_response


async def proxy_http(
    request: web.Request,
    session: ClientSession,
    target: str,
    forwarded_headers: bool,
) -> web.StreamResponse:
    """Proxy regular HTTP requests to Home Assistant."""

    data = await request.read()
    async with session.request(
        request.method,
        upstream_url(target, request),
        headers=proxy_headers(
            request,
            target,
            forwarded_headers=forwarded_headers,
        ),
        data=data,
        allow_redirects=False,
    ) as upstream:
        response = web.StreamResponse(
            status=upstream.status,
            reason=upstream.reason,
            headers=response_headers(upstream.headers),
        )
        try:
            await response.prepare(request)
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
        except ClientConnectionResetError:
            pass
        return response


@asynccontextmanager
async def client_session() -> AsyncIterator[ClientSession]:
    """Yield the shared upstream HTTP client."""

    async with ClientSession(auto_decompress=False) as session:
        yield session


async def main_async() -> None:
    """Run the HTTPS reverse proxy."""

    args = parse_args()
    target = target_base_url(args.target)
    cert_path, key_path = ensure_localhost_certificate(args.cert_dir)
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(cert_path, key_path)

    async with client_session() as session:
        async def handler(request: web.Request) -> web.StreamResponse:
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return await proxy_websocket(
                    request,
                    session,
                    target,
                    args.forwarded_headers,
                )
            return await proxy_http(request, session, target, args.forwarded_headers)

        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_route("*", "/{path_info:.*}", handler)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port, ssl_context=ssl_context)
        await site.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)

        sys.stdout.write(f"HA HTTPS proxy ready: https://{args.host}:{args.port}\n")
        sys.stdout.write(
            "Open this URL in the browser and accept the local test certificate.\n"
        )
        sys.stdout.flush()
        await stop_event.wait()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(runner.cleanup(), timeout=3.0)


def main() -> None:
    """Entrypoint."""

    with suppress(KeyboardInterrupt):
        asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
