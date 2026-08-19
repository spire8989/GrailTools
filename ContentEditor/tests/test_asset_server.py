from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

import sys

CONTENT_EDITOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONTENT_EDITOR))

import server  # noqa: E402


GRAIL = CONTENT_EDITOR.parents[1] / "Grail"


class AssetServerTests(unittest.TestCase):
    def test_multipart_binary_png_reaches_image_preview_and_upload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grail-asset-server-") as temp_name:
            project = Path(temp_name) / "Grail"
            shutil.copytree(GRAIL, project)
            backup_dir = Path(temp_name) / "backups"
            original_backup_directory = server.backup_directory
            server.backup_directory = lambda: backup_dir
            self.addCleanup(lambda: setattr(server, "backup_directory", original_backup_directory))
            http_server = server.ThreadingHTTPServer(("127.0.0.1", 0), server.EditorHandler)
            http_server.project_root = project  # type: ignore[attr-defined]
            thread = threading.Thread(target=http_server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(lambda: (http_server.shutdown(), http_server.server_close(), thread.join(timeout=2)))

            image_buffer = BytesIO()
            Image.new("RGB", (1122, 1402), (70, 90, 120)).save(image_buffer, format="PNG")
            body = self.multipart_body({
                "assetType": "image",
                "category": "portrait",
                "assetId": "portrait_http_upload",
                "optimizeForGame": "true",
                "optimizationProfile": "portrait",
                "cropAnchor": "center",
            }, "portrait.png", image_buffer.getvalue())

            connection = http.client.HTTPConnection("127.0.0.1", http_server.server_port, timeout=10)
            connection.request("POST", "/api/assets/upload", body=body, headers={
                "Content-Type": "multipart/form-data; boundary=asset-test-boundary",
                "Content-Length": str(len(body)),
            })
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200, payload)
            self.assertEqual(payload["assetResult"]["path"], "assets/images/portrait/portrait.webp")
            with Image.open(project / payload["assetResult"]["path"]) as output:
                self.assertEqual(output.size, (480, 600))
                self.assertEqual(output.format, "WEBP")
            server.backup_directory = original_backup_directory

    @staticmethod
    def multipart_body(fields: dict[str, str], filename: str, content: bytes) -> bytes:
        boundary = b"asset-test-boundary"
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.extend([
                b"--" + boundary + b"\r\n",
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8") + b"\r\n",
            ])
        parts.extend([
            b"--" + boundary + b"\r\n",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode("utf-8"),
            content + b"\r\n",
            b"--" + boundary + b"--\r\n",
        ])
        return b"".join(parts)


if __name__ == "__main__":
    unittest.main()
