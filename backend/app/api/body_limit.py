from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class UploadBodyLimit:
    """Enforce a byte limit even for chunked bodies without Content-Length."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        maximum = self.max_bytes if scope.get("path") == "/api/documents/upload" else 1024 * 1024
        received = 0
        started = False

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise BodyTooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except BodyTooLarge:
            if not started:
                await JSONResponse(
                    {"detail": "Request body exceeds the configured byte limit."}, status_code=413
                )(scope, receive, send)
            else:
                raise
