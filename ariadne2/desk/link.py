"""The desk's end of the socket: GLib only, so it lives in GTK's main loop."""
from __future__ import annotations

import logging
from typing import Callable

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .. import protocol  # noqa: E402

log = logging.getLogger("ariadne2.desk.link")

BACKOFF_MIN = 0.5
BACKOFF_MAX = 5.0


class CoreLink:
    def __init__(self, on_message: Callable[[dict], None],
                 on_status: Callable[[str], None], path=None) -> None:
        self._on_message = on_message
        self._on_status = on_status
        self._path = str(path) if path else str(protocol.socket_path())
        self._backoff = BACKOFF_MIN
        self._conn: Gio.SocketConnection | None = None
        self._input: Gio.DataInputStream | None = None
        self._output: Gio.OutputStream | None = None
        self._cancel: Gio.Cancellable | None = None
        self._retry_id = 0
        self._writing = False
        self._outbox: list[bytes] = []
        self._stopped = True

    # -- public --

    def start(self) -> None:
        self._stopped = False
        self._connect()

    def stop(self) -> None:
        self._stopped = True
        if self._retry_id:
            GLib.source_remove(self._retry_id)
            self._retry_id = 0
        self._close()

    def send(self, msg: dict) -> bool:
        if self._output is None:
            return False        # dropped on purpose: a stale click shouldn't fire later
        try:
            self._outbox.append(protocol.encode(msg))
        except Exception:
            log.exception("could not encode %r", msg)
            return False
        self._pump()
        return True

    # -- connecting --

    def _connect(self) -> None:
        self._cancel = Gio.Cancellable()
        cancel = self._cancel
        try:
            Gio.SocketClient.new().connect_async(
                Gio.UnixSocketAddress.new(self._path), cancel, self._on_connect, cancel)
        except Exception:
            log.exception("connect failed to start")
            self._lost(cancel)

    def _on_connect(self, client, result, cancel) -> None:
        if cancel is not self._cancel:
            return
        try:
            conn = client.connect_finish(result)
        except Exception as e:
            log.debug("connect failed: %s", e)
            self._lost(cancel)
            return
        try:
            self._conn = conn
            self._input = Gio.DataInputStream.new(conn.get_input_stream())
            self._output = conn.get_output_stream()
            self._backoff = BACKOFF_MIN
            self._on_status("connected")
            self.send(protocol.hello_desk())
            self._read(cancel)
        except Exception:
            log.exception("setup after connect failed")
            self._lost(cancel)

    # -- reading --

    def _read(self, cancel) -> None:
        self._input.read_line_async(GLib.PRIORITY_DEFAULT, cancel, self._on_line, cancel)

    def _on_line(self, stream, result, cancel) -> None:
        if cancel is not self._cancel:
            return
        try:
            # the utf8 variant gives None at EOF; the bytes variant gives b'' (looks like a blank line)
            raw, _ = stream.read_line_finish_utf8(result)
        except GLib.Error as e:
            if e.matches(GLib.ConvertError.quark(), GLib.ConvertError.ILLEGAL_SEQUENCE):
                log.warning("core line not utf-8, skipped")
                self._read(cancel)
                return
            log.debug("read failed: %s", e)
            self._lost(cancel)
            return
        except Exception as e:
            log.debug("read failed: %s", e)
            self._lost(cancel)
            return
        if raw is None:         # EOF: the core went away
            self._lost(cancel)
            return
        try:
            msg = protocol.decode(raw)
        except protocol.ProtocolError as e:
            log.warning("bad core line skipped: %s", e)
        else:
            try:
                self._on_message(msg)
            except Exception:
                log.exception("on_message raised")
        if cancel is self._cancel:
            try:
                self._read(cancel)
            except Exception:
                log.exception("could not continue reading")
                self._lost(cancel)

    # -- writing --

    def _pump(self) -> None:
        # One write at a time: Gio refuses overlapping operations on a stream.
        if self._writing or not self._outbox or self._output is None:
            return
        data = self._outbox.pop(0)
        self._writing = True
        cancel = self._cancel
        try:
            self._output.write_all_async(
                data, GLib.PRIORITY_DEFAULT, cancel, self._on_written, cancel)
        except Exception:
            log.exception("write failed to start")
            self._writing = False
            self._lost(cancel)

    def _on_written(self, stream, result, cancel) -> None:
        if cancel is not self._cancel:
            return
        self._writing = False
        try:
            stream.write_all_finish(result)
        except Exception as e:
            log.debug("write failed: %s", e)
            self._lost(cancel)
            return
        self._pump()

    # -- losing the connection --

    def _close(self) -> None:
        if self._cancel:
            self._cancel.cancel()
        self._cancel = None
        conn, self._conn = self._conn, None
        self._input = self._output = None
        self._outbox.clear()
        self._writing = False
        if conn is not None:
            try:
                conn.close(None)
            except Exception:
                pass

    def _lost(self, cancel) -> None:
        if cancel is not self._cancel or self._stopped:
            return
        self._close()
        self._on_status("reconnecting")
        delay = self._backoff
        self._backoff = min(self._backoff * 2, BACKOFF_MAX)
        self._retry_id = GLib.timeout_add(int(delay * 1000), self._retry)

    def _retry(self) -> bool:
        self._retry_id = 0
        if not self._stopped:
            self._connect()
        return False
