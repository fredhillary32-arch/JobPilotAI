"""Server-side request body limits, enforced before a body is parsed or spooled."""
import re

from fastapi import HTTPException, status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.documents import MAX_DOCUMENT_SIZE_BYTES

# Uploads may carry a full-size document plus multipart framing and form fields.
UPLOAD_BODY_LIMIT_BYTES = MAX_DOCUMENT_SIZE_BYTES + 512 * 1024
# Every other request is JSON well below this (job descriptions are ≤ 50,000 characters).
DEFAULT_BODY_LIMIT_BYTES = 1024 * 1024
UPLOAD_PATH = re.compile(r"^/api/v1/candidate-profiles/[^/]+/documents/?$")
TOO_LARGE_DETAIL = "The request body is too large."


def body_limit_for(method: str, path: str) -> int:
    if method == "POST" and UPLOAD_PATH.match(path):
        return UPLOAD_BODY_LIMIT_BYTES
    return DEFAULT_BODY_LIMIT_BYTES


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = body_limit_for(scope["method"], scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = True
            if too_large:
                await _reject(send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raised while the framework reads the body, before it is spooled.
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=TOO_LARGE_DETAIL,
                    )
            return message

        await self.app(scope, limited_receive, send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"' + TOO_LARGE_DETAIL.encode() + b'"}'
    await send({
        "type": "http.response.start",
        "status": status.HTTP_413_CONTENT_TOO_LARGE,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": body})
