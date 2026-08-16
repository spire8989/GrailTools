"""Local HTTP entry point for the standalone Grail Content Editor."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from content_editor_core import JsParseError, load_catalog, merged_state, save_catalog, validate_catalog


TOOL_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = TOOL_ROOT / "static"
DEFAULT_PROJECT = TOOL_ROOT.parents[1] / "Grail"


class EditorHandler(BaseHTTPRequestHandler):
    server_version = "GrailContentEditor/1.0"

    @property
    def project_root(self) -> Path:
        return self.server.project_root  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/catalog":
            self._json_response(load_catalog(self.project_root))
            return
        if path == "/api/health":
            self._json_response({"ok": True, "projectRoot": str(self.project_root)})
            return
        if path in {"/", "/index.html"}:
            self._static_response(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            target = (STATIC_ROOT / relative).resolve()
            if STATIC_ROOT.resolve() in target.parents and target.is_file():
                content_type = {
                    ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".html": "text/html; charset=utf-8",
                }.get(target.suffix, "application/octet-stream")
                self._static_response(target, content_type)
                return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/validate":
                current = load_catalog(self.project_root)
                values = merged_state(current, payload)
                validation = validate_catalog(values, current["known"], current["references"])
                self._json_response(validation)
                return
            if path == "/api/save":
                result = save_catalog(
                    self.project_root,
                    payload,
                    expected_hashes=payload.get("sourceHashes"),
                    backup_dir=TOOL_ROOT / ".backups",
                )
                self._json_response(result)
                return
            self.send_error(404, "Not found")
        except FileNotFoundError as error:
            self._json_response({"error": f"Missing Grail source file: {error}"}, status=500)
        except (JsParseError, ValueError, RuntimeError) as error:
            message = str(error)
            try:
                details = json.loads(message)
            except json.JSONDecodeError:
                details = {"error": message}
            self._json_response(details, status=409 if "Conflict:" in message else 400)
        except Exception as error:  # pragma: no cover - defensive server boundary
            self._json_response({"error": f"Unexpected editor server error: {error}"}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("[ContentEditor] " + (format % args) + "\n")

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length") from error
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _json_response(self, payload: object, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _static_response(self, path: Path, content_type: str) -> None:
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Grail Content Editor")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT, help="Path to the sibling Grail project")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5173, help="Port (default: 5173)")
    arguments = parser.parse_args()
    project_root = arguments.project.expanduser().resolve()
    if not project_root.is_dir():
        parser.error(f"Grail project directory does not exist: {project_root}")
    http_server = ThreadingHTTPServer((arguments.host, arguments.port), EditorHandler)
    http_server.project_root = project_root  # type: ignore[attr-defined]
    print(f"Grail Content Editor: http://{arguments.host}:{arguments.port}/")
    print(f"Grail project: {project_root}")
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Content Editor")
    finally:
        http_server.server_close()


if __name__ == "__main__":
    main()
