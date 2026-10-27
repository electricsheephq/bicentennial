"""The director's loopback-only HTTP edge. handle() ledgers before anything is sent; a failed send is counted in
send_errors, never ledgered. If handle raises (a ledger failure, or on_hold raised), nothing is sent."""

import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _handler(director):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet; the ledger is the log
            pass

        def _gone(self) -> bool:
            try:  # a client that already hung up reads b""
                ready, _, _ = select.select([self.connection], [], [], 0)
                return bool(ready) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def _serve(self):
            given = self.headers.get("Content-Length") or "0"
            self.close_connection |= not given.isdigit()  # an unreadable length: an empty, refused body
            raw = self.rfile.read(int(given)) if given.isdigit() and self.command != "CONNECT" else b""
            try:
                status, headers, body = director.handle(self.command, self.path, self.headers, raw, peek=self._gone)
            except BaseException:
                self.close_connection = True
                return
            try:
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
            except OSError:
                self.close_connection = True
                director.note_send_error()
            if self.command == "CONNECT":
                self.close_connection = True

        do_GET = do_POST = do_CONNECT = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _serve

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True


def serve(director, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 only (port 0 picks one, published as server.port) and serve on a background thread."""
    server = _Server(("127.0.0.1", port), _handler(director))
    server.port = server.server_address[1]
    director.bind_port(server.port)
    server.thread = threading.Thread(target=server.serve_forever, name="director", daemon=True)
    server.thread.start()
    return server


def shutdown(server) -> None:
    server.shutdown()
    server.server_close()
    server.thread.join()
