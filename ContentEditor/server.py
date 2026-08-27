"""Local HTTP entry point for the standalone Grail Content Editor."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from content_editor_core import JsParseError, load_catalog, merged_state, preview_image, save_catalog, upload_asset, validate_catalog


TOOL_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = TOOL_ROOT / "static"
DEFAULT_PROJECT = TOOL_ROOT.parents[1] / "Grail"


def backup_directory() -> Path:
    """Return a writable recovery-backup directory for this editor process."""
    preferred = TOOL_ROOT / ".backups"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / f".write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
        return preferred
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "GrailContentEditorBackups"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


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
        if path == "/api/assets/file":
            requested = parse_qs(urlparse(self.path).query).get("path", [""])[0]
            target = (self.project_root / unquote(requested)).resolve()
            assets_root = (self.project_root / "assets" / "images").resolve()
            if assets_root not in target.parents or not target.is_file():
                self.send_error(404, "Asset not found")
                return
            content_type = {
                ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".avif": "image/avif",
            }.get(target.suffix.lower(), "application/octet-stream")
            self._static_response(target, content_type)
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
            if path in {"/api/assets/preview", "/api/assets/upload", "/api/assets/replace"}:
                fields, filename, content, sam_mask_json = self._read_multipart()
                sam_mask_json = sam_mask_json or fields.get("samMaskJson")
                asset_type = fields.get("assetType", "")
                category = fields.get("category", "")
                asset_id = fields.get("assetId", "")
                if asset_type != "image":
                    raise ValueError("Only image assets can be uploaded.")
                if not filename or content is None:
                    raise ValueError("Choose a file before uploading an asset.")
                optimize_for_game = fields.get("optimizeForGame", "true" if path == "/api/assets/preview" else "false").lower() in {"1", "true", "yes", "on"}
                optimization_profile = fields.get("optimizationProfile") or None
                crop_anchor = fields.get("cropAnchor") or "center"
                if path == "/api/assets/preview":
                    self._json_response(preview_image(
                        category=category,
                        filename=filename,
                        content=content,
                        optimize_for_game=optimize_for_game,
                        optimization_profile=optimization_profile,
                        crop_anchor=crop_anchor,
                        sam_mask_json=sam_mask_json,
                    ))
                    return
                result = upload_asset(
                    self.project_root,
                    asset_type=asset_type,
                    category=category,
                    asset_id=asset_id,
                    filename=filename,
                    content=content,
                    expected_hash=fields.get("sourceHash") or None,
                    replace=path.endswith("/replace"),
                    backup_dir=backup_directory(),
                    optimize_for_game=optimize_for_game,
                    optimization_profile=optimization_profile,
                    crop_anchor=crop_anchor,
                    sam_mask_json=sam_mask_json,
                )
                self._json_response(result)
                return
            payload = self._read_json()
            if path == "/api/validate":
                current = load_catalog(self.project_root)
                values = merged_state(current, payload)
                validation = validate_catalog(values, current["known"], current["references"], project_root=self.project_root)
                self._json_response(validation)
                return
            if path == "/api/save":
                result = save_catalog(
                    self.project_root,
                    payload,
                    expected_hashes=payload.get("sourceHashes"),
                    backup_dir=backup_directory(),
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

    def _read_multipart(self) -> tuple[dict[str, str], str | None, bytes | None, str | None]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 64 * 1024 * 1024:
            raise ValueError("Upload is empty or exceeds the 64 MB editor limit.")
        content_type = self.headers.get("Content-Type", "")
        pieces = [piece.strip() for piece in content_type.split(";")]
        boundary_value = next((piece.split("=", 1)[1].strip('"') for piece in pieces[1:] if piece.startswith("boundary=")), None)
        if not boundary_value:
            raise ValueError("Expected a multipart upload.")
        body = self.rfile.read(content_length)
        delimiter = b"--" + boundary_value.encode("utf-8")
        fields: dict[str, str] = {}
        filename: str | None = None
        content: bytes | None = None
        sam_mask_json: str | None = None
        for part in body.split(delimiter)[1:]:
            if part.startswith(b"--"):
                break
            part = part.lstrip(b"\r\n")
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            raw_headers = part[:header_end].decode("utf-8", errors="replace")
            value = part[header_end + 4:]
            if value.endswith(b"\r\n"):
                value = value[:-2]
            disposition = next((line for line in raw_headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
            params = {}
            for item in disposition.split(";", 1)[1].split(";") if ";" in disposition else []:
                if "=" in item:
                    key, raw_value = item.strip().split("=", 1)
                    params[key] = raw_value.strip().strip('"')
            field_name = params.get("name")
            if not field_name:
                continue
            # Browsers normally include filename= on the binary part, but the
            # field name is the reliable signal across Chromium/Firefox and
            # prevents us from ever decoding image bytes as UTF-8.
            if field_name == "file":
                filename = params.get("filename") or params.get("filename*")
                content = value
            elif field_name in {"samMaskFile", "samMask"} or ("filename" in params and Path(params.get("filename", "")).suffix.lower() == ".json"):
                sam_mask_json = value.decode("utf-8")
            else:
                fields[field_name] = value.decode("utf-8")
        return fields, filename, content, sam_mask_json

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
