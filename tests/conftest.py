"""
Pytest fixtures and config.
"""
import asyncio
import sys

import pytest

from aiosmtplib import SMTP
from testserver import SMTPPresetServer, TestHandler, TestSMTPD


PY36_OR_LATER = sys.version_info[:2] >= (3, 6)
PY37_OR_LATER = sys.version_info[:2] >= (3, 7)
try:
    import uvloop
except ImportError:
    HAS_UVLOOP = False
else:
    HAS_UVLOOP = True


def pytest_addoption(parser):
    parser.addoption(
        "--event-loop", action="store", default="asyncio", choices=["asyncio", "uvloop"]
    )


@pytest.fixture()
def event_loop(request):
    loop_type = request.config.getoption("--event-loop")
    if loop_type == "uvloop" and not HAS_UVLOOP:
        raise RuntimeError("uvloop not installed.")

    if loop_type == "asyncio":
        loop = asyncio.new_event_loop()
    elif loop_type == "uvloop":
        loop = uvloop.new_event_loop()
    else:
        raise ValueError("Unknown event loop type: {}".format(loop_type))

    yield loop

    # Cancel any pending tasks
    if PY37_OR_LATER:
        cleanup_tasks = asyncio.all_tasks(loop=loop)
    else:
        cleanup_tasks = asyncio.Task.all_tasks(loop=loop)

    if cleanup_tasks:
        for task in cleanup_tasks:
            task.cancel()
        try:
            loop.run_until_complete(
                asyncio.wait(cleanup_tasks, loop=loop, timeout=0.01)
            )
        except RuntimeError:
            # Event loop was probably already stopping.
            pass

    if PY36_OR_LATER:
        loop.run_until_complete(loop.shutdown_asyncgens())

    loop.call_soon(loop.stop)
    loop.run_forever()

    loop.close()


@pytest.fixture(scope="function")
def messages_recieved(request):
    return []


@pytest.fixture()
def hostname(request):
    return "localhost"


@pytest.fixture()
def port(request, unused_tcp_port):
    """Alias for ununsed_tcp_port."""
    return unused_tcp_port


@pytest.fixture(scope="function")
def smtpd_handler(request, messages_recieved):
    return TestHandler(messages_recieved)


@pytest.fixture()
def smtpd_server(request, event_loop, hostname, port, smtpd_handler):
    def factory():
        return TestSMTPD(smtpd_handler, enable_SMTPUTF8=False)

    server = event_loop.run_until_complete(
        event_loop.create_server(factory, host=hostname, port=port)
    )

    def close_server():
        server.close()
        event_loop.run_until_complete(server.wait_closed())

    request.addfinalizer(close_server)

    return server


@pytest.fixture()
def preset_server(request, event_loop, unused_tcp_port):
    server = SMTPPresetServer("localhost", unused_tcp_port, loop=event_loop)

    event_loop.run_until_complete(server.start())

    def close_server():
        event_loop.run_until_complete(server.stop())

    request.addfinalizer(close_server)

    return server


@pytest.fixture()
def smtpd_client(request, smtpd_server, event_loop, hostname, port):
    client = SMTP(hostname=hostname, port=port, loop=event_loop, timeout=1)

    return client


@pytest.fixture()
def preset_client(request, preset_server, event_loop, hostname, port):
    client = SMTP(hostname=hostname, port=port, loop=event_loop, timeout=1)
    client.server = preset_server

    return client
