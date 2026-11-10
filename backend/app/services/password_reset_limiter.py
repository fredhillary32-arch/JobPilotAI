from threading import Lock

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

PASSWORD_RESET_REQUEST_LIMIT = parse("5 per 15 minutes")
PASSWORD_RESET_CLIENT_LIMIT = parse("20 per 15 minutes")


class PasswordResetLimiter:
    def __init__(self) -> None:
        self._storage = MemoryStorage()
        self._limiter = MovingWindowRateLimiter(self._storage)
        self.lock = Lock()

    def is_limited(self, client_ip: str) -> bool:
        return not (
            self._limiter.test(PASSWORD_RESET_REQUEST_LIMIT, client_ip)
            and self._limiter.test(PASSWORD_RESET_CLIENT_LIMIT, client_ip)
        )

    def record_request(self, client_ip: str) -> None:
        self._limiter.hit(PASSWORD_RESET_REQUEST_LIMIT, client_ip)
        self._limiter.hit(PASSWORD_RESET_CLIENT_LIMIT, client_ip)

    def reset(self) -> None:
        self._storage.reset()


password_reset_limiter = PasswordResetLimiter()
