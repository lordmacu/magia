#!/usr/bin/env python3
"""live_cfl.py — TV EN VIVO 100% Python via el CDN Cloudflare (sign_type=cfl), igual que VOD.

Descubrimiento (2026-08-09b): el vivo NO necesita el redirect /slb a nvuos (P2SP) ni Función A.
get_slb(live) trae una entrada CDN `sign_type=cfl` (Cloudflare directo). El media es:
    GET http://<cfl_host>/live/<channel>.m3u8          (playlist, Content-Auth header)
    GET http://<seg_host>/live/<channel>/<seg>.ts       (segmentos, Content-Auth con sign_o3)
Los segmentos apuntan a hosts CDN variables (absolutos en el m3u8) y requieren un `sign2`
fresco (sign_o3) por request. Este módulo levanta un proxy HLS local que re-firma cada
segmento -> se abre directo en VLC/mpv.

Uso:  python3 live_cfl.py <channel_code>        (ej: cyx_50fdcc0817d61_720p)
      python3 live_cfl.py <channel_code> --play  (lanza mpv)
"""
import sys, os, re, time, json, threading
import http.server, urllib.parse
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iptv_client import IPTVClient
from sign_o3 import sign_o3, now_moment_ms
requests.packages.urllib3.disable_warnings()

UA = "Ranger/4.9.4-17294ac0"
APP = os.environ.get("IPTV_APP_ID", "com.android.msandroid")
AVER = os.environ.get("IPTV_APK_VERSION", "49902")


def resolve_live_cfl(client, channel_code):
    """Devuelve (cfl_host, cfl_auth_url, content_license, token) para el canal via CDN cfl."""
    pl = client.play_live(channel_code)
    addrs = pl.get("liveAddressList", []) if isinstance(pl, dict) else []
    if not addrs:
        raise RuntimeError(f"play_live sin liveAddressList: {str(pl)[:120]}")
    license_str = addrs[0].get("license", "")
    slb = client.get_slb(type_="merge", live_codes=[channel_code])
    for cdn in slb.get("cdn_list", []):
        if cdn.get("tag") != "live":
            continue
        for u in cdn.get("url_list", []):
            url = u.get("url", "")
            if "sign_type=cfl" in url:
                host = cdn.get("main_addr", "").replace("http://", "").replace("https://", "").split("/")[0]
                m = re.search(r"token=([0-9A-Fa-f]{32})", url)
                return host, url, license_str, (m.group(1) if m else "")
    raise RuntimeError("no hay entrada CDN cfl para live en get_slb")


def _seg_auth(cfl_url, token):
    mom = now_moment_ms()
    s2 = sign_o3(token, mom)
    return f"{cfl_url}&sign2_method=sign_o3&instance=0&start_moment={mom}&sign2={s2}"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _hdrs(self, auth, lic):
        return {"Content-Auth": auth, "Content-License": lic, "User-Agent": UA,
                "App": APP, "App-Version": AVER, "X-Buffer": "0"}

    def do_GET(self):
        srv = self.server
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.endswith(".m3u8"):
            # (re)fetch del playlist en vivo y reescritura de segmentos -> proxy
            url = f"http://{srv.cfl_host}/live/{srv.channel}.m3u8"
            auth = _seg_auth(srv.cfl_url, srv.token)
            try:
                r = requests.get(url, headers=self._hdrs(auth, srv.license), timeout=12)
            except Exception as e:
                self.send_error(502, str(e)); return
            if r.status_code != 200:
                self.send_error(r.status_code); return
            body = self._rewrite(r.text)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass
        elif parsed.path == "/seg":
            q = urllib.parse.parse_qs(parsed.query)
            seg_url = q.get("u", [""])[0]
            if not seg_url:
                self.send_error(400); return
            auth = _seg_auth(srv.cfl_url, srv.token)
            try:
                r = requests.get(seg_url, headers=self._hdrs(auth, srv.license), timeout=20, stream=True)
            except Exception as e:
                self.send_error(502, str(e)); return
            self.send_response(r.status_code)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            try:
                for chunk in r.iter_content(65536):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError): pass
        else:
            self.send_error(404)

    def _rewrite(self, text):
        out = []
        for ln in text.splitlines():
            s = ln.strip()
            if s.startswith("http") and ".ts" in s:
                out.append(f"http://127.0.0.1:{self.server.server_address[1]}/seg?u={urllib.parse.quote(s, safe='')}")
            else:
                out.append(ln)
        return ("\n".join(out) + "\n").encode()


def start_proxy(cfl_host, cfl_url, license_str, token, channel, port=0):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.cfl_host = cfl_host; httpd.cfl_url = cfl_url; httpd.license = license_str
    httpd.token = token; httpd.channel = channel
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main():
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("uso: python3 live_cfl.py <channel_code> [--play]"); sys.exit(1)
    channel = sys.argv[1]
    client = IPTVClient()
    host, url, lic, token = resolve_live_cfl(client, channel)
    print(f"[cfl] host={host} token={token}")
    httpd, port = start_proxy(host, url, lic, token, channel)
    local = f"http://127.0.0.1:{port}/play.m3u8"
    print(f"[cfl] proxy en vivo: {local}")
    if "--play" in sys.argv:
        os.system(f"mpv --cache=yes '{local}' >/dev/null 2>&1 || open -a VLC '{local}'")
    else:
        print("[cfl] abrí esa URL en VLC/mpv. Ctrl-C para salir.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
