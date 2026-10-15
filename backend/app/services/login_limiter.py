from threading import Lock

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

LOGIN_FAILURE_LIMIT = parse("5 per 15 minutes")


class LoginFailureLimiter:
    def __init__(self) -> None:
        self._storage = MemoryStorage()
        self._limiter = MovingWindowRateLimiter(self._storage)
        self.lock = Lock()

    @staticmethod
    def _key(client_ip: str) -> str:
        return LOGIN_FAILURE_LIMIT.key_for(client_ip)

    def is_limited(self, client_ip: str) -> bool:
        return not self._limiter.test(
            LOGIN_FAILURE_LIMIT,
            self._key(client_ip),
        )

    def record_failure(self, client_ip: str) -> None:
        self._limiter.hit(
            LOGIN_FAILURE_LIMIT,
            self._key(client_ip),
        )

    def reset(self) -> None:
        self._storage.reset()


login_failure_limiter = LoginFailureLimiter()
