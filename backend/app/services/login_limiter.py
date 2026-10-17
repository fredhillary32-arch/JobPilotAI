from threading import Lock

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

# Failed sign-ins are counted per client and account, so one person's mistakes
# behind a shared address (such as the Vite proxy on 127.0.0.1) do not lock
# out other accounts. A wider per-client cap still slows guessing across many
# accounts from one client.
LOGIN_FAILURE_LIMIT = parse("5 per 15 minutes")
CLIENT_FAILURE_LIMIT = parse("50 per 15 minutes")


class LoginFailureLimiter:
    def __init__(self) -> None:
        self._storage = MemoryStorage()
        self._limiter = MovingWindowRateLimiter(self._storage)
        self.lock = Lock()

    def is_limited(self, client_ip: str, account: str) -> bool:
        return not (
            self._limiter.test(LOGIN_FAILURE_LIMIT, client_ip, account)
            and self._limiter.test(CLIENT_FAILURE_LIMIT, client_ip)
        )

    def record_failure(self, client_ip: str, account: str) -> None:
        self._limiter.hit(LOGIN_FAILURE_LIMIT, client_ip, account)
        self._limiter.hit(CLIENT_FAILURE_LIMIT, client_ip)

    def clear_account(self, client_ip: str, account: str) -> None:
        """Forget this client's failures for an account after a successful sign-in."""
        self._limiter.clear(LOGIN_FAILURE_LIMIT, client_ip, account)

    def reset(self) -> None:
        self._storage.reset()


login_failure_limiter = LoginFailureLimiter()
