import importlib
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.test import override_settings
from redis import Redis
from redis.exceptions import RedisError


@pytest.fixture
def temporary_redis(tmp_path):
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for the concurrent throttle test.")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    process = subprocess.Popen(
        [
            executable,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = Redis(host="127.0.0.1", port=port, decode_responses=True)
    deadline = time.monotonic() + 5
    while True:
        try:
            client.ping()
            break
        except RedisError:
            if time.monotonic() >= deadline:
                process.terminate()
                process.wait(timeout=5)
                pytest.fail("Temporary Redis server did not start.")
            time.sleep(0.02)

    try:
        yield client
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)


def test_concurrent_login_attempts_are_atomically_limited(
    temporary_redis,
    monkeypatch,
) -> None:
    auth_module = importlib.import_module("core.services.authenticate_user")
    monkeypatch.setattr(auth_module, "_get_redis_client", lambda: temporary_redis)
    monkeypatch.setattr(auth_module, "authenticate", lambda **kwargs: None)

    def attempt() -> str:
        try:
            auth_module.authenticate_user("same-user", "wrong", "127.0.0.1")
        except auth_module.LoginRateLimited:
            return "blocked"
        return "allowed"

    with (
        override_settings(
            LOGIN_RATE_LIMIT_ATTEMPTS=5,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS=900,
        ),
        ThreadPoolExecutor(max_workers=10) as pool,
    ):
        results = list(pool.map(lambda _: attempt(), range(10)))

    assert results.count("allowed") == 5
    assert results.count("blocked") == 5
