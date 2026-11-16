from __future__ import annotations

import hashlib
import hmac
from typing import Protocol

from django.conf import settings
from django.contrib.auth import authenticate
from redis import Redis

from accounts.models import User


class LoginRateLimited(Exception):
    pass


_RATE_LIMIT_SCRIPT = """
local attempts = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if attempts >= limit then
    return 0
end
local updated = redis.call('INCR', KEYS[1])
if updated == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 1
"""


class _RedisClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int: ...

    def delete(self, name: str) -> int: ...


def _get_redis_client() -> _RedisClient:
    redis_url = getattr(
        settings,
        "LOGIN_RATE_LIMIT_REDIS_URL",
        settings.QUEUE_REDIS_URL,
    )
    return Redis.from_url(redis_url, decode_responses=True)


def _rate_limit_key(username: str, remote_addr: str) -> str:
    value = f"{username.strip().casefold()}:{remote_addr}"
    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"login-rate-limit:{digest}"


def authenticate_user(
    username: str,
    password: str,
    remote_addr: str,
) -> User | None:
    client = _get_redis_client()
    key = _rate_limit_key(username, remote_addr)
    max_attempts = settings.LOGIN_RATE_LIMIT_ATTEMPTS
    window_seconds = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS

    allowed = client.eval(
        _RATE_LIMIT_SCRIPT,
        1,
        key,
        max_attempts,
        window_seconds,
    )
    if not allowed:
        raise LoginRateLimited

    user = authenticate(username=username.strip(), password=password)
    if user is None:
        return None

    client.delete(key)
    return user
