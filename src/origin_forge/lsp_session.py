from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import BinaryIO

from .lsp_protocol import (
    DEFAULT_MAX_MESSAGE_BYTES,
    LspProtocolError,
    encode_lsp_message,
    read_lsp_message,
)


class LspRequestTimeout(TimeoutError):
    pass


class LspSessionClosed(LspProtocolError):
    pass


class LspRemoteError(LspProtocolError):
    def __init__(self, code: int, message: str, data: object | None = None):
        super().__init__(f"LSP remote error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class LspNotification:
    method: str
    params: object | None


@dataclass(frozen=True)
class _Failure:
    error: BaseException


class LspJsonRpcSession:
    """Bounded synchronous JSON-RPC session over existing LSP byte streams.

    Exactly one client request may be outstanding. Server notifications are
    buffered under a hard count limit. Server-to-client requests are rejected
    with JSON-RPC MethodNotFound until Origin Forge explicitly implements a
    safe handler for a specific method.

    A request timeout makes the session terminal. Once response correlation is
    uncertain, the owner must replace the session rather than risk consuming a
    late response as evidence for a later request.
    """

    def __init__(
        self,
        reader: BinaryIO,
        writer: BinaryIO,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        max_pending_notifications: int = 256,
    ):
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        if max_pending_notifications <= 0:
            raise ValueError("max_pending_notifications must be positive")
        self.reader = reader
        self.writer = writer
        self.max_message_bytes = max_message_bytes
        self.max_pending_notifications = max_pending_notifications
        self._responses: queue.Queue[dict | _Failure] = queue.Queue()
        self._notifications: deque[LspNotification] = deque()
        self._notification_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._fatal_lock = threading.Lock()
        self._next_id = 1
        self._closed = False
        self._fatal: BaseException | None = None
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="origin-forge-lsp-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _fatal_error(self) -> BaseException | None:
        with self._fatal_lock:
            return self._fatal

    def _write_message(self, payload: dict) -> None:
        if self._closed:
            raise LspSessionClosed("LSP session is closed")
        encoded = encode_lsp_message(
            payload,
            max_message_bytes=self.max_message_bytes,
        )
        with self._write_lock:
            try:
                self.writer.write(encoded)
                self.writer.flush()
            except (OSError, ValueError) as exc:
                raise LspSessionClosed(f"cannot write LSP message: {exc}") from exc

    def _set_fatal(self, error: BaseException) -> None:
        with self._fatal_lock:
            if self._fatal is not None:
                return
            self._fatal = error
        self._responses.put(_Failure(error))

    def _raise_if_fatal(self) -> None:
        error = self._fatal_error()
        if error is not None:
            raise error

    def _reject_server_request(self, message: dict) -> None:
        request_id = message.get("id")
        self._write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "Origin Forge does not allow this server request",
                },
            }
        )

    def _reader_loop(self) -> None:
        try:
            while not self._closed:
                message = read_lsp_message(
                    self.reader,
                    max_message_bytes=self.max_message_bytes,
                )
                if message.get("jsonrpc") != "2.0":
                    raise LspProtocolError(
                        "LSP message must declare jsonrpc='2.0'"
                    )
                method = message.get("method")
                if isinstance(method, str):
                    if "id" in message:
                        self._reject_server_request(message)
                        continue
                    with self._notification_lock:
                        if len(self._notifications) >= self.max_pending_notifications:
                            raise LspProtocolError(
                                "LSP pending notification limit exceeded"
                            )
                        self._notifications.append(
                            LspNotification(method, message.get("params"))
                        )
                    continue
                if "id" not in message:
                    raise LspProtocolError(
                        "LSP response is missing both method and id"
                    )
                self._responses.put(message)
        except EOFError as exc:
            if not self._closed:
                self._set_fatal(LspSessionClosed(str(exc)))
        except BaseException as exc:
            if not self._closed:
                self._set_fatal(exc)

    def request(
        self,
        method: str,
        params: object | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> object | None:
        if not method:
            raise ValueError("LSP request method may not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._raise_if_fatal()

        with self._request_lock:
            self._raise_if_fatal()
            request_id = self._next_id
            self._next_id += 1
            payload: dict = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                payload["params"] = params
            self._write_message(payload)

            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    error = LspRequestTimeout(f"LSP request timed out: {method}")
                    self._set_fatal(error)
                    raise error
                try:
                    response = self._responses.get(timeout=remaining)
                except queue.Empty as exc:
                    error = LspRequestTimeout(f"LSP request timed out: {method}")
                    self._set_fatal(error)
                    raise error from exc
                if isinstance(response, _Failure):
                    raise response.error
                if response.get("id") != request_id:
                    error = LspProtocolError(
                        f"unexpected LSP response id {response.get('id')!r}; expected {request_id!r}"
                    )
                    self._set_fatal(error)
                    raise error
                if "error" in response:
                    raw = response["error"]
                    if not isinstance(raw, dict):
                        raise LspProtocolError("malformed LSP error response")
                    code = raw.get("code")
                    message = raw.get("message")
                    if not isinstance(code, int) or not isinstance(message, str):
                        raise LspProtocolError("malformed LSP error response")
                    raise LspRemoteError(code, message, raw.get("data"))
                return response.get("result")

    def notify(self, method: str, params: object | None = None) -> None:
        if not method:
            raise ValueError("LSP notification method may not be empty")
        self._raise_if_fatal()
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._write_message(payload)

    def take_notifications(self) -> tuple[LspNotification, ...]:
        with self._notification_lock:
            values = tuple(self._notifications)
            self._notifications.clear()
        return values

    def close(self) -> None:
        self._closed = True
