#!/usr/bin/env python3
"""
live_stream.py — Streaming de TV en vivo de Magis TV SIN app ni emulador.

Reemplaza al proxy Ranger de la app: levanta un proxy HTTP local que sirve el .m3u8 y,
para CADA segmento .ts, construye un `Content-Auth` fresco (start_moment nuevo + sign2
calculado con `sign_o3`) y baja del CDN real. Así VLC/mpv apuntan al proxy local y todo
se firma en Python puro.

Depende de: sign_o3.py (calcula el sign2 vía emulación Unicorn del transform del .so).

Flujo:
    LiveSession(host, auth_prefix, content_license, ranger_id) describe la sesión CDN
    (lo que entrega get_slb(live) + play_live). El proxy usa esa sesión para re-firmar.
"""
import http.server
import re
import socketserver
import threading
import time
import urllib.request

from sign_o3 import sign_o3, now_moment_ms

CDN_PORT = 8119
UA = "Ranger/4.9.4-17294ac0"


class LiveSession:
    """Parámetros de sesión CDN para un canal (de get_slb(live) + play_live)."""

    def __init__(self, host, auth_prefix, content_license, ranger_id="",
                 app_id="com.android.msandroid", app_ver="49902"):
        # host: "149.34.241.153:8119"
        # auth_prefix: el Content-Auth SIN "&start_moment=...&sign2=..." (termina en "&instance=0")
        #   ej: "/live/?user_id=...&trans_id=...&...&token=<tok>&sign2_method=sign_o3&instance=0"
        self.host = host
        self.auth_prefix = auth_prefix.split("&start_moment=")[0]
        self.content_license = content_license
        self.ranger_id = ranger_id
        self.app_id = app_id
        self.app_ver = app_ver
        m = re.search(r"&token=([0-9a-f]{32})", self.auth_prefix)
        if not m:
            raise ValueError("auth_prefix sin token lowercase")
        self.token = m.group(1)

    def content_auth(self, moment=None):
        """Content-Auth fresco con start_moment nuevo + sign2 (sign_o3)."""
        moment = moment or now_moment_ms()
        s2 = sign_o3(self.token, moment)
        return f"{self.auth_prefix}&start_moment={moment}&sign2={s2}"

    def headers(self, moment=None):
        h = {
            "Host": self.host,
            "Connection": "Keep-Alive",
            "App": self.app_id,
            "App-Version": self.app_ver,
            "Content-Auth": self.content_auth(moment),
            "Content-License": self.content_license,
            "Pragma": "akamai-x-cache-on",
            "User-Agent": UA,
            "X-Buffer": "0",
        }
        if self.ranger_id:
            h["Ranger-Id"] = self.ranger_id
        return h

    def fetch(self, path, timeout=15):
        """GET http://<host><path> con Content-Auth fresco. Devuelve (status, headers, body)."""
        url = f"http://{self.host}{path}"
        req = urllib.request.Request(url, headers=self.headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, {}, e.read()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        sess = self.server.session
        path = self.path
        status, hdrs, body = sess.fetch(path)
        if status != 200:
            self.send_response(status)
            self.end_headers()
            return
        # Si es m3u8, reescribir las rutas de segmento para que pasen por el proxy.
        if path.endswith(".m3u8") or b"#EXTM3U" in body[:16]:
            body = self._rewrite_m3u8(body)
            ctype = "application/vnd.apple.mpegurl"
        else:
            ctype = hdrs.get("Content-Type", "video/mp2t")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _rewrite_m3u8(self, body):
        """Las líneas de segmento son rutas relativas (cyx_.../...ts). Se dejan relativas:
        VLC las pedirá al proxy (mismo host:puerto) y las re-firmamos. Solo aseguramos que
        las URIs absolutas al CDN (si las hubiera) apunten al proxy."""
        text = body.decode("utf-8", "replace")
        host = self.server.server_address
        base = f"http://{host[0]}:{host[1]}/live/"
        # rutas relativas de segmento -> /live/<ruta> (el .m3u8 se sirvió desde /live/<canal>.m3u8)
        out = []
        for ln in text.splitlines():
            if ln and not ln.startswith("#"):
                if ln.startswith("http"):
                    ln = re.sub(r"https?://[^/]+/", base, ln)
                else:
                    ln = "/live/" + ln.lstrip("/")
            out.append(ln)
        return ("\n".join(out) + "\n").encode()


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LiveProxy:
    """Proxy local que re-firma cada request del CDN con sign_o3."""

    def __init__(self, session: LiveSession, bind="127.0.0.1", port=0):
        self.session = session
        self.httpd = _ThreadingServer((bind, port), _Handler)
        self.httpd.session = session
        self.port = self.httpd.server_address[1]
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def url_for(self, channel_media_code):
        # channel_media_code: "cyx_60E823A918E082251749_720p" (sin extensión)
        return f"http://127.0.0.1:{self.port}/live/{channel_media_code}.m3u8"

    def stop(self):
        self.httpd.shutdown()
