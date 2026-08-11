#!/usr/bin/env python3
"""El CLI no debe anunciar 'Streaming' ni abrir el player si el canal no responde.

Se levantan servidores HTTP de verdad (sin mocks) que imitan al proxy local en cada
escenario: playlist OK, canal no autorizado (401), error del CDN y proxy caido.
"""
import http.server
import threading
import unittest

import magia


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"#EXTM3U\n#EXT-X-VERSION:3\n"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.status != 200:
            self.send_error(self.status)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)


def _serve(status):
    handler = type("H", (_Handler,), {"status": status})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/play.m3u8"


class LivePlaylistProbe(unittest.TestCase):
    def test_returns_none_when_playlist_is_served(self):
        httpd, url = _serve(200)
        try:
            self.assertIsNone(magia.live_playlist_error(url))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_reports_unauthorized_channel(self):
        httpd, url = _serve(401)
        try:
            msg = magia.live_playlist_error(url)
            self.assertIsNotNone(msg, "un 401 tiene que reportarse, no pasar de largo")
            self.assertIn("401", msg)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_reports_cdn_failure(self):
        httpd, url = _serve(502)
        try:
            msg = magia.live_playlist_error(url)
            self.assertIsNotNone(msg)
            self.assertIn("502", msg)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_reports_dead_proxy(self):
        httpd, url = _serve(200)
        httpd.shutdown()
        httpd.server_close()                       # nadie escuchando en ese puerto
        msg = magia.live_playlist_error(url, timeout=3)
        self.assertIsNotNone(msg, "si el proxy no responde hay que decirlo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
