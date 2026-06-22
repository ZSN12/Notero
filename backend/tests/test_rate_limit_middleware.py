"""Tests for the Redis-backed sliding-window rate limit middleware."""

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/auth/register")
    def register():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class FakePipeline:
    """A pipeline that operates on a shared in-memory sorted set."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self._ops = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))
        return self

    def zcard(self, key):
        self._ops.append(("zcard", key))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def zrange(self, key, start, end, withscores=False):
        self._ops.append(("zrange", key, start, end, withscores))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            name = op[0]
            key = op[1]
            data = self.redis._data.setdefault(key, [])
            if name == "zremrangebyscore":
                max_score = op[3]
                data[:] = [item for item in data if item[0] > max_score]
                results.append(0)
            elif name == "zadd":
                mapping = op[2]
                for member, score in mapping.items():
                    data.append((score, member))
                results.append(1)
            elif name == "zcard":
                results.append(len(data))
            elif name == "expire":
                results.append(True)
            elif name == "zrange":
                sorted_data = sorted(data, key=lambda x: x[0])
                if op[4]:  # withscores
                    results.append([[member, score] for score, member in sorted_data])
                else:
                    results.append([member for _, member in sorted_data])
        self._ops.clear()
        return results


class FakeRedis:
    """In-memory Redis with just enough sorted-set support for rate limiting."""

    def __init__(self):
        self._data: dict[str, list[tuple[float, str]]] = {}

    def pipeline(self):
        return FakePipeline(self)

    def zrem(self, key, member):
        data = self._data.get(key, [])
        self._data[key] = [item for item in data if item[1] != member]


@pytest.fixture
def fake_redis():
    return FakeRedis()


class TestMemoryFallback:
    def test_allows_requests_within_limit(self, client):
        with patch("app.middleware.rate_limit.get_redis", return_value=None):
            for _ in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200
                assert int(resp.headers["X-RateLimit-Limit"]) == 5

    def test_blocks_after_limit(self, client):
        with patch("app.middleware.rate_limit.get_redis", return_value=None):
            for _ in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200

            resp = client.get("/api/auth/register")
            assert resp.status_code == 429
            assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_unlimited_paths_are_not_counted(self, client):
        with patch("app.middleware.rate_limit.get_redis", return_value=None):
            for _ in range(10):
                resp = client.get("/api/health")
                assert resp.status_code == 200
                assert "X-RateLimit-Limit" not in resp.headers


class TestRedisPath:
    def test_allows_requests_within_redis_limit(self, client, fake_redis):
        with patch("app.middleware.rate_limit.get_redis", return_value=fake_redis):
            for i in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200
                assert int(resp.headers["X-RateLimit-Limit"]) == 5
                assert int(resp.headers["X-RateLimit-Remaining"]) == 4 - i

    def test_blocks_after_redis_limit(self, client, fake_redis):
        with patch("app.middleware.rate_limit.get_redis", return_value=fake_redis):
            for _ in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200

            resp = client.get("/api/auth/register")
            assert resp.status_code == 429
            assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_falls_back_to_memory_when_redis_command_raises(self, client):
        redis_client = MagicMock()
        redis_client.pipeline.side_effect = RuntimeError("Redis down")

        with patch("app.middleware.rate_limit.get_redis", return_value=redis_client):
            for _ in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200

            resp = client.get("/api/auth/register")
            assert resp.status_code == 429

    def test_falls_back_to_memory_when_get_redis_raises(self, client):
        with patch(
            "app.middleware.rate_limit.get_redis", side_effect=RuntimeError("Redis down")
        ):
            for _ in range(5):
                resp = client.get("/api/auth/register")
                assert resp.status_code == 200

            resp = client.get("/api/auth/register")
            assert resp.status_code == 429


class TestUserKey:
    def test_same_token_produces_same_user_key(self):
        middleware = RateLimitMiddleware(None)
        scope = {"type": "http", "headers": [(b"authorization", b"Bearer secret-token")]}
        req1 = Request(scope)
        req2 = Request(scope)
        assert middleware._get_user_key(req1) == middleware._get_user_key(req2)
        # The raw token should never appear in the key.
        assert "secret-token" not in middleware._get_user_key(req1)

    def test_different_tokens_produce_different_user_keys(self):
        middleware = RateLimitMiddleware(None)
        scope1 = {"type": "http", "headers": [(b"authorization", b"Bearer token-one")]}
        scope2 = {"type": "http", "headers": [(b"authorization", b"Bearer token-two")]}
        assert middleware._get_user_key(Request(scope1)) != middleware._get_user_key(
            Request(scope2)
        )


class TestSharedAcrossInstances:
    def test_multiple_instances_share_redis_counter(self, fake_redis):
        """Two middleware instances with the same Redis should share the window."""

        def make_app():
            app = FastAPI()
            app.add_middleware(RateLimitMiddleware)

            @app.get("/api/auth/register")
            def register():
                return {"ok": True}

            return app

        app1 = make_app()
        app2 = make_app()

        with patch("app.middleware.rate_limit.get_redis", return_value=fake_redis):
            with TestClient(app1) as client1, TestClient(app2) as client2:
                # 3 requests through instance 1
                for _ in range(3):
                    assert client1.get("/api/auth/register").status_code == 200
                # 2 requests through instance 2 (total 5)
                for _ in range(2):
                    assert client2.get("/api/auth/register").status_code == 200
                # 6th request through either instance should be blocked
                assert client1.get("/api/auth/register").status_code == 429
