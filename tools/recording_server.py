"""Small local HTTP(S) API and static server for participant recording."""
from __future__ import annotations

import argparse
import json
import logging
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from common.core import setup_logging
from common.participant_recording import ParticipantStore

WEB_ROOT = Path(__file__).resolve().parent / "recording_web"
MAX_BODY = 10 * 1024 * 1024


class RecordingHandler(BaseHTTPRequestHandler):
    store: ParticipantStore

    def log_message(self, fmt, *args):
        # Never log registration bodies, roll numbers, or names.
        logging.info("recording-server %s", fmt % args)

    def _json(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _body(self):
        try: size = int(self.headers.get("Content-Length", "0"))
        except ValueError: raise ValueError("Invalid content length.")
        if size < 1 or size > MAX_BODY: raise ValueError("Request body is empty or too large.")
        return self.rfile.read(size)

    def _token(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "): raise ValueError("Please register again to continue.")
        return header[7:]

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/": return self._static("index.html", "text/html; charset=utf-8")
        if parsed.path == "/static/app.js": return self._static("app.js", "text/javascript; charset=utf-8")
        if parsed.path == "/static/style.css": return self._static("style.css", "text/css; charset=utf-8")
        if parsed.path == "/api/session":
            try:
                query = parse_qs(parsed.query)
                language = query.get("language", [""])[0].lower()
                session = int(query.get("session", [""])[0])
                plan = self.store.session_plan(self._token(), language, session)
                return self._json(200, plan)
            except ValueError as exc: return self._json(400, {"error": str(exc)})
            except Exception: logging.exception("Could not load recording session"); return self._json(500, {"error": "Could not load this session."})
        return self._json(404, {"error": "Not found."})

    def _static(self, name, content_type):
        path = WEB_ROOT / name
        try: payload = path.read_bytes()
        except OSError: return self._json(404, {"error": "Recording interface file not found."})
        self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(payload))); self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.wfile.write(payload)

    def do_POST(self):
        route = urlsplit(self.path).path
        if route == "/api/logout":
            try:
                self.store.logout(self._token())
                return self._json(200, {"ok": True})
            except ValueError as exc: return self._json(400, {"error": str(exc)})
        if route == "/api/register":
            try:
                body = json.loads(self._body().decode("utf-8"))
                result = self.store.participant(body.get("name", ""), body.get("roll_number", ""))
                return self._json(200, result)
            except ValueError as exc: return self._json(400, {"error": str(exc)})
            except Exception: logging.exception("Participant registration failed"); return self._json(500, {"error": "Registration could not be saved. Please contact the researcher."})
        if route == "/api/upload":
            try:
                token = self._token()
                language = self.headers.get("X-Language", "").lower()
                session = int(self.headers.get("X-Session", "0"))
                utterance_id = self.headers.get("X-Utterance-ID", "")
                result = self.store.accept_upload(token, language, session, utterance_id, self._body())
                return self._json(201, result)
            except FileExistsError as exc: return self._json(409, {"error": str(exc)})
            except ValueError as exc: return self._json(400, {"error": str(exc)})
            except Exception: logging.exception("Recording upload failed"); return self._json(500, {"error": "Recording could not be saved. Please contact the researcher."})
        return self._json(404, {"error": "Not found."})


def serve(host="127.0.0.1", port=8000, config=None, certfile=None, keyfile=None):
    if (certfile is None) != (keyfile is None):
        raise ValueError("Provide both --certfile and --keyfile for HTTPS.")
    if host not in ("127.0.0.1", "localhost", "::1") and not certfile:
        raise ValueError("Binding beyond this computer requires HTTPS; provide --certfile and --keyfile.")
    server = ThreadingHTTPServer((host, port), RecordingHandler)
    RecordingHandler.store = ParticipantStore(config)
    scheme = "http"
    if certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile, keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    logging.info("Participant recorder listening at %s://%s:%s", scheme, host, port)
    try: server.serve_forever()
    except KeyboardInterrupt: logging.info("Stopping participant recorder")
    finally: server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local participant recording website")
    parser.add_argument("--host", default="127.0.0.1", help="Use 127.0.0.1 locally; use 0.0.0.0 only with HTTPS for LAN access")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config")
    parser.add_argument("--certfile", help="TLS certificate for HTTPS access")
    parser.add_argument("--keyfile", help="TLS private key for HTTPS access")
    args = parser.parse_args(); setup_logging()
    try: serve(args.host, args.port, args.config, args.certfile, args.keyfile)
    except (OSError, ValueError) as exc: parser.error(str(exc))
