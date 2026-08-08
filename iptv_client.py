#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente Python que replica el protocolo completo del app IPTV
==============================================================
APK:      Xuper.Hydra.HDR.4KP.apk  (package com.xuper.netxxus / marca interna "brasiliptv" / portal "masnew")
Backend:  portal tipo IPTV chino (ijkplayer + ARouter + ANet).  Endpoints  {scheme}://{host}/api/portalCore/...

Descubierto por decompilación (jadx/apktool) + análisis dinámico (Frida como oráculo de crypto) del propio APK.

Protocolo:
  * Request  body  = hex( base64( 3DES-ede/ECB/PKCS5( json_enriquecido ) ) )
  * Response .data  = mismo esquema (se descifra igual)
  * A CADA body se le agregan ~16 campos de dispositivo (interceptor C6357b)
  * Headers obligatorios: apk / apkVer / spkgVer   (si faltan -> "版本已停止使用")
  * Clave 3DES: se lee de la variable de entorno IPTV_3DES_KEY (ver .env)
  * userToken es EFÍMERO (lo emite el server en active/login) -> ver refrescar_token()

Requiere:  pip install pycryptodome requests
"""
import base64
import json
import os
import sys
import requests
from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad, unpad
from pathlib import Path

requests.packages.urllib3.disable_warnings()

# ─────────────────────────────  .env loader  ─────────────────────────────
def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if key and val and key not in os.environ:
            os.environ[key] = val

_load_dotenv()


# ─────────────────────────────  CRYPTO  ─────────────────────────────
KEY_3DES = None

def _init_key():
    global KEY_3DES
    if KEY_3DES is not None:
        return
    _key_hex = os.environ.get("IPTV_3DES_KEY", "")
    if not _key_hex:
        raise RuntimeError("IPTV_3DES_KEY not set. Run the setup wizard or copy .env.example to .env and fill in the values.")
    KEY_3DES = bytes.fromhex(_key_hex)


def encrypt_body(plain: str) -> str:
    """json (str) -> hex(base64(3DES-ECB(json)))  == cuerpo que espera el server."""
    _init_key()
    ct = DES3.new(KEY_3DES, DES3.MODE_ECB).encrypt(pad(plain.encode("utf-8"), 8))
    b64 = base64.b64encode(ct).decode("ascii")
    return b64.encode("ascii").hex()


def decrypt_blob(wire: str) -> str:
    """hex(base64(3DES(json))) -> json (str).  Sirve para el campo .data de las respuestas."""
    _init_key()
    inner = bytes.fromhex(wire).decode("ascii", "ignore")
    ct = base64.b64decode(inner)
    return unpad(DES3.new(KEY_3DES, DES3.MODE_ECB).decrypt(ct), 8).decode("utf-8", "ignore")


# ─────────────────────────────  CLIENTE  ────────────────────────────
class IPTVClient:
    HOSTS = os.environ.get("IPTV_HOSTS", "").split(",")

    def __init__(self, user_id=None, user_token=None, portal="masnew", auto_activate=True):
        if not self.HOSTS or not self.HOSTS[0]:
            raise RuntimeError("IPTV_HOSTS not set. Copy .env.example to .env and fill in the values.")
        self.user_id = user_id or ""
        self.user_token = user_token or ""
        self.portal = portal
        self.host = self.HOSTS[0]
        self.s = requests.Session()
        self.s.verify = False
        app_id = os.environ.get("IPTV_APP_ID", "")
        apk_ver = os.environ.get("IPTV_APK_VERSION", "")
        if not app_id:
            raise RuntimeError("IPTV_APP_ID not set. Check your .env file.")
        self.device = {
            "loginType": "2", "appLanguage": "en", "apkVersion": apk_ver,
            "sysVersion": "2025-08-07 05:40:11_36_16_", "appId": app_id,
            "hardwareInfo": "ranchu", "model": "sdk_gphone64_arm64", "product": "sdk_gphone64_arm64",
            "cpu": "arm64-v8a", "B29": "",
            "reserve1": os.environ.get("IPTV_DEVICE_RESERVE1", ""),
            "deviceToken": os.environ.get("IPTV_DEVICE_TOKEN", ""),
            "sn": os.environ.get("IPTV_DEVICE_SN", ""),
            "drmId": os.environ.get("IPTV_DEVICE_DRM_ID", ""),
            "sdkVer": 36,
        }
        self.headers = {
            "Content-Type": "application/json;charset=utf-8",
            "apk": app_id, "apkVer": "43404",
            "spkgVer": "2025-08-07 05:40:11_36_16_", "User-Agent": "okhttp/3.12.12",
        }
        if auto_activate and not self.user_token:
            self.activate()

    # ---- transporte ----
    def call(self, path, bean=None, base_fields=True):
        body = {}
        if base_fields:
            body.update({"portalCode": self.portal, "userId": self.user_id, "userToken": self.user_token})
        if bean:
            body.update(bean)
        body.update(self.device)                       # enriquecer
        wire = encrypt_body(json.dumps(body, separators=(",", ":")))
        last = None
        for host in [self.host] + [h for h in self.HOSTS if h != self.host]:
            try:
                r = self.s.post(f"https://{host}/api/portalCore/{path}",
                                data=wire, headers=self.headers, timeout=15)
                j = json.loads(r.text)
                rc = j.get("returnCode")
                if rc not in ("0", None):
                    return {"_error": rc, "_msg": j.get("errorMessage"), "_path": path}
                if isinstance(j.get("data"), str) and j["data"]:
                    return json.loads(decrypt_blob(j["data"]))
                return j
            except Exception as e:
                last = e
        return {"_exception": str(last), "_path": path}

    # ─────────────  ACTIVACIÓN / SESIÓN  ─────────────
    def activate(self):
        """Activación autónoma por device `sn` (tier free): mintea un userToken fresco.
        signdata/matadata van VACÍOS (solo los STB con /system/etc/.UCERT los llevan)."""
        bean = {"snToken": "", "authVersion": "", "authCode": "", "preCode": "",
                "macAddr": "02:00:00:00:00:00", "reserve1": self.device["reserve1"],
                "openNum": 4, "channel": "default", "matadata": "", "signdata": ""}
        r = self.call("v8/active", bean, base_fields=False)
        if isinstance(r, dict) and r.get("userToken"):
            self.user_id = r["userId"]
            self.user_token = r["userToken"]
            self.jwt = r.get("jwtToken", "")
        return r

    def use_account(self, user_id, user_token):
        """Fija una sesión de CUENTA ya logueada (obtenida con login manual + captura del token)."""
        self.user_id = user_id; self.user_token = user_token; return self

    def login(self, username, enc_password, account_type="2", type_="1", area_code=""):
        """Login por cuenta email.  Parámetros REALES observados: accountType='2', type='1'.
        OJO: `enc_password` NO es la clave en claro — el app la cifra a base64(DES/3DES(pwd+salt))
        con AbstractC1235i (claves DES '==RiXVKU' / 'dCsPLwiy'). El input lleva un prefijo/salt
        (cipher de 40 bytes), por lo que aquí se espera el password YA cifrado como lo manda el app.
        Método fiable en la práctica: loguear en el app y capturar el userToken (ver README)."""
        bean = {"accountType": account_type, "userName": username, "password": enc_password, "type": type_,
                "macAddr": "02:00:00:00:00:00", "areaCode": area_code, "verificationCode": "",
                "verificationToken": "", "matadata": "", "signdata": "", "channel": "default"}
        r = self.call("v8/login", bean, base_fields=False)
        if isinstance(r, dict) and r.get("userToken"):
            self.user_id = r["userId"]; self.user_token = r["userToken"]
        return r

    def get_slb(self, type_="merge", live_codes=None, has_pay="0"):
        """SLB / balanceo: devuelve cdn_list con los hosts CDN reales (main_addr) por tag (vod/live/record)."""
        return self.call("v14/getSlbInfo", {"hasPay": has_pay, "userIdentity": "1", "type": type_,
                         "appVer": os.environ.get("IPTV_APK_VERSION", ""), "lang": "es", "encMediaSupported": 1,
                         "liveCodeList": live_codes or ["masnew_live"], "appParams": "",
                         "reserve1": "02:00:00:00:00:00", "pipFlag": "0"})

    def cdn_hosts(self):
        """Resumen {tag: [main_addr,...]} de los CDN donde vive el media real (detrás del proxy local)."""
        out = {}
        for cdn in self.get_slb().get("cdn_list", []):
            out.setdefault(cdn.get("tag"), []).append(cdn.get("main_addr"))
        return out

    # ─────────────  CONFIG  ─────────────
    def config(self, group="ApkConfig", module="Config"):
        return self.call("config/get", {"groupName": group, "moduleName": module})

    def base_time(self):
        return self.call("getBaseTime", {})

    def heartbeat(self):
        return self.call("v5/heartbeat", {})

    def auth_info(self, content_id, type_="1", lang="en"):
        return self.call("v9/getAuthInfo", {"type": type_, "lang": lang}) if not content_id else \
               self.call("v9/getAuthInfo", {"type": type_, "lang": lang})

    # ─────────────  LISTADOS / CATÁLOGOS  ─────────────
    def home(self, home_page_code="", version=""):
        return self.call("getHome", {"homePageCode": home_page_code, "version": version})

    def next_columns(self, column_code, page=1, size=50, version=""):
        return self.call("getNextColumns", {"columnCode": column_code, "pageNum": page,
                                            "pageSize": size, "version": version})

    def column_contents(self, column_id, page=1, size=30, special="", num_display=0, is_av1=""):
        # columnId: Integer ; specialFlag/isAv1: String
        return self.call("v3/getColumnContents", {"columnId": int(column_id), "pageNum": page, "pageSize": size,
                         "specialFlag": str(special), "numDisplay": num_display, "isAv1": str(is_av1)})

    def shelve_data(self, column_id, column_type="", page=1, size=30, num_display=0):
        return self.call("v3/getShelveData", {"columnId": column_id, "columnType": column_type,
                         "pageNum": page, "pageSize": size, "numDisplay": num_display, "encryptVersion": ""})

    def filter_genre(self, lang="en"):
        return self.call("v3/filterGenre", {"language": lang})

    def filter_by_content(self, column_id, tags="", year="", language="", audio="",
                          original_country="", page=1, size=30):
        return self.call("v3/filterByContent", {"columnId": column_id, "tags": tags, "year": year,
                         "language": language, "audio": audio, "originalCountry": original_country,
                         "pageNum": page, "pageSize": size})

    # ─────────────  BÚSQUEDA  ─────────────
    def search(self, value, type_="0", column_id="", page=1, size=20, filt=""):
        return self.call("v3/searchByName", {"value": value, "type": type_, "columnId": column_id,
                         "filter": filt, "pageNum": page, "pageSize": size})

    def search_resource_or_person(self, value, type_="0", page=1, size=20):
        return self.call("searchResourceOrPerson", {"value": value, "type": type_,
                         "pageNum": page, "pageSize": size})

    def live_search(self, value, page=1, size=20):
        return self.call("liveSearchByName", {"value": value, "pageNum": page, "pageSize": size})

    # ─────────────  SIMILARES / RECOMENDADOS  ─────────────
    def similar(self, content_id, type_="0", start=0, rows=10, end=50):
        """'searchByContent' = contenido similar/relacionado a un item."""
        return self.call("v3/searchByContent", {"contentId": content_id, "type": type_,
                         "start": start, "rows": rows, "end": end})

    def recommends(self, codes):
        return self.call("v3/getRecommends", {"recommendCodeArr": codes})

    def person(self, content_id, type_="0", imdb=""):
        return self.call("getPerson", {"contentId": content_id, "type": type_, "imdb": imdb,
                         "macAddr": "02:00:00:00:00:00"})

    def items_by_person(self, pu_id, type_="0", page=1, size=30):
        return self.call("getItemByPerson", {"puId": pu_id, "type": type_, "pageNum": page,
                         "pageSize": size, "macAddr": "02:00:00:00:00:00"})

    # ─────────────  DETALLE  ─────────────
    def detail(self, content_id, type_="1", sort_type="0", lang="en"):
        return self.call("v4/getItemData", {"contentId": content_id, "type": type_, "sortType": sort_type,
                         "language": lang, "macAddr": "02:00:00:00:00:00"})

    # ─────────────  REPRODUCCIÓN  ─────────────
    def play_vod(self, content_id, series_content_id="", start_time=0, type_="1", column_id=0, auth_type=""):
        """Devuelve movieList[].{contentId,license,videoFormat,quality} + subtítulos.
        La URL real la sirve un proxy local (127.0.0.1:PORT/vod/0/<id>.m3u8) que baja del CDN con el license."""
        return self.call("v10/startPlayVOD", {"contentId": content_id, "seriesContentId": series_content_id,
                         "startTime": start_time, "type": type_, "columnId": column_id, "authType": auth_type})

    def play_live(self, channel_code, column_id=0, type_="1"):
        """Devuelve liveAddressList[].{playCode,license,cdnType,AVFormat} para el canal en vivo."""
        return self.call("v4/startPlayLive", {"channelCode": channel_code, "columnId": column_id, "type": type_})

    # ─────────────  HELPERS DE ALTO NIVEL (peli / serie / live) ─────────────
    def episodes(self, series_id):
        """Lista de episodios de una serie (teleplay).  -> [{contentId, name, seriesNumber, ...}]"""
        d = self.detail(series_id, type_="0")
        return d.get("assetData", {}).get("simpleProgramList", [])

    def watch(self, content_id, program_type="movie"):
        """Punto único de reproducción que maneja PELÍCULA y SERIE.
        movie    -> startPlayVOD(contentId)
        teleplay -> detail(type=0) -> primer episodio -> startPlayVOD(ep, series=contentId)"""
        if program_type in ("teleplay", "series", "variety"):
            eps = self.episodes(content_id)
            if not eps:
                return {"_error": "sin episodios", "series": content_id}
            ep = eps[0]
            play = self.play_vod(ep["contentId"], series_content_id=content_id, type_="1")
            return {"kind": "serie", "series": content_id, "episode": ep.get("name"),
                    "episodeId": ep["contentId"], "totalEpisodes": len(eps), "play": play}
        play = self.play_vod(content_id, type_="1")
        return {"kind": "pelicula", "contentId": content_id, "play": play}

    def play_btv(self, channel_code, content_id, column_id=0, type_="0"):
        return self.call("v6/startPlayBTV", {"channelCode": channel_code, "contentId": content_id,
                         "columnId": column_id, "type": type_})

    # ─────────────  LIVE / EPG (TV IP)  ─────────────
    def live_categories(self):
        """Categorías de TV en vivo (ChannelList, Deportes, Colombia, ...)."""
        return self.next_columns("masnew_live", size=30)

    def live_data(self, column_id=76182, page=1, size=1000, data_version="", expire=""):
        """Lista de canales de TV IP.  columnId 76182 = 'ChannelList' (todos los canales del inicio)."""
        return self.call("v6/getLiveData", {"columnId": int(column_id), "pageNum": page, "pageSize": size,
                         "dataVersion": data_version, "expireTimeStr": expire})

    def epg(self, channel_code, column_id=0, type_="2"):
        return self.call("v3/getProgram", {"channelCode": channel_code, "columnId": column_id, "type": type_})

    # ─────────────  FAVORITOS / USUARIO  ─────────────
    def favorites(self, query_type="all", bl_flag="0"):
        return self.call("getFavorite", {"queryType": query_type, "blFlag": bl_flag})

    def add_favorite(self, content_ids, type_="1", bl_flag="0"):
        return self.call("v2/addFavorite", {"contentIdList": content_ids, "type": type_, "blFlag": bl_flag})

    def order_info(self):
        return self.call("package/getOrderInfo", {})

    def devices(self, tem_token=""):
        return self.call("device-management/getDevice", {"temToken": tem_token}, base_fields=False)


# ─────────────────────────────  DEMO / CLI  ─────────────────────────
def _title(t): print("\n" + "═" * 4 + " " + t + " " + "═" * (60 - len(t)))


def _search_items(sr):
    out = []
    for grp in sr.get("searchItemList", []):
        out.extend(grp.get("itemList", []))
    return out or sr.get("assetList") or sr.get("list") or []


def demo(c: IPTVClient):
    """Recorre el flujo completo: config -> catálogo -> listado -> búsqueda -> detalle -> similares -> reproducción."""
    _title("CONFIG")
    cfg = c.config(); print("returnCode ok:", "_error" not in cfg)

    _title("CATÁLOGO: sub-columnas de MOVIES  (getNextColumns 'masnew_movies')")
    nc = c.next_columns("masnew_movies", size=10)
    cols = nc.get("recommendList", [])
    print("sub-columnas:", len(cols))
    for col in cols[:6]:
        print("  -", col.get("columnId"), "| type", col.get("type"), "|", col.get("name"))

    demo_cid = "11A43548F9CC4E39A342CABD7D673AD9"   # fallback (Star Wars: Mandalorian & Grogu)
    for col in cols:                                # buscar una columna paginable (type 1/2) con contenido
        cid = col.get("columnId")
        lst = c.column_contents(cid, size=8)
        items = lst.get("contentList") or lst.get("list") or lst.get("assetList") or []
        if items:
            _title(f"LISTADO de columna {cid} ({col.get('name')})")
            for it in items[:8]:
                print("  •", it.get("contentId"), "|", it.get("name"))
            demo_cid = items[0].get("contentId") or demo_cid
            break

    _title("BÚSQUEDA 'star'")
    hits = _search_items(c.search("star", size=8))
    for h in hits[:8]:
        print("  •", h.get("contentId"), "|", h.get("name"), "|", h.get("programType"))
    movie = next((h for h in hits if h.get("programType") == "movie"), hits[0] if hits else None)
    if movie:
        demo_cid = movie.get("contentId") or demo_cid
        print("  -> elegimos la PELÍCULA:", movie.get("name"), demo_cid)

    _title(f"DETALLE de {demo_cid}")
    d = c.detail(demo_cid)
    asset = d.get("assetData", d)
    print("  nombre :", asset.get("name"))
    print("  género :", asset.get("tags"))
    print("  dir.   :", asset.get("director"), "| cast:", (asset.get("actorDisplay") or "")[:60])
    print("  calidad:", (asset.get("simpleProgramList") or [{}])[0].get("quality"))

    _title(f"SIMILARES a {demo_cid}")
    sim = c.similar(demo_cid, rows=6)
    for h in (sim.get("assetList") or sim.get("list") or [])[:6]:
        print("  ~", h.get("contentId"), "|", h.get("name"))

    _title(f"REPRODUCIR PELÍCULA {demo_cid}  (startPlayVOD)")
    _show_vod(c.play_vod(demo_cid))

    # ---- SERIE ----
    _title("SERIE: buscar 'star' -> teleplay -> episodios -> reproducir")
    series = next((h for h in hits if h.get("programType") == "teleplay"), None)
    if series:
        sid = series["contentId"]
        eps = c.episodes(sid)
        print(f"  serie: {series['name']}  ({len(eps)} episodios)")
        for e in eps[:4]:
            print("    ep", e.get("seriesNumber"), "-", e.get("name"), e.get("contentId"))
        if eps:
            w = c.watch(sid, "teleplay")
            print(f"  reproduciendo episodio 1 ({w.get('episode')}):")
            _show_vod(w.get("play", {}))

    # ---- TV EN VIVO (la "TV IP" del inicio) ----
    _title("TV EN VIVO: categorías -> canales -> reproducir (startPlayLive)")
    cats = c.live_categories().get("recommendList", [])
    print("  categorías live:", ", ".join(x.get("name", "") for x in cats[:6]))
    ld = c.live_data()
    chans = ld.get("channelList", [])
    print(f"  canales (columna ChannelList): {len(chans)}")
    for ch in chans[:5]:
        print("    •", ch.get("channelCode"), "|", ch.get("name"))
    if chans:
        ch = chans[1] if len(chans) > 1 else chans[0]
        _title(f"REPRODUCIR CANAL {ch.get('name')}  ({ch.get('channelCode')})")
        live = c.play_live(ch["channelCode"])
        for a in live.get("liveAddressList", [])[:2]:
            print("  cdnType", a.get("cdnType"), "| fmt", a.get("AVFormat"),
                  "| playCode", a.get("playCode"))
            print("    LICENSE:", a.get("license"))


def _show_vod(play):
    try:
        ep = play["episodeList"][0]
        movie = ep["totalMovieList"][0]["movieList"][0]
        print("  media contentId:", movie["contentId"])
        print("  formato        :", movie.get("videoFormat"), movie.get("encodeFormat"), movie.get("quality"))
        print("  audio          :", movie.get("audioInfo"))
        print("  LICENSE        :", movie["licenseList"][0]["license"])
        for s in ep.get("subtitleList", []):
            print("  subt", s["language"], ":", s["file"][0]["url"])
        print("  -> reproductor: http://127.0.0.1:<port>/vod/0/<sessionId>.m3u8  (proxy local + CDN con el license)")
    except Exception:
        print("  respuesta:", json.dumps(play, ensure_ascii=False)[:400])


if __name__ == "__main__":
    # Sin token -> el cliente se ACTIVA solo (mintea userToken por el sn del device)
    c = IPTVClient()
    print(f"[activado] userId={c.user_id}  userToken={c.user_token}\n")

    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "cdn":
        print(json.dumps(c.cdn_hosts(), ensure_ascii=False, indent=2)); raise SystemExit
    if a == "search":
        print(json.dumps(c.search(" ".join(sys.argv[2:]) or "star"), ensure_ascii=False, indent=2)[:3000])
    elif a == "play":       # película:  play <contentId>
        print(json.dumps(c.play_vod(sys.argv[2]), ensure_ascii=False, indent=2)[:3000])
    elif a == "detail":
        print(json.dumps(c.detail(sys.argv[2], type_=sys.argv[3] if len(sys.argv) > 3 else "1"),
                         ensure_ascii=False, indent=2)[:3000])
    elif a == "series":     # serie:  series <seriesId>   (lista episodios)
        for e in c.episodes(sys.argv[2]):
            print(e.get("seriesNumber"), e.get("name"), e.get("contentId"))
    elif a == "watch":      # watch <contentId> [movie|teleplay]
        print(json.dumps(c.watch(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "movie"),
                         ensure_ascii=False, indent=2)[:3000])
    elif a == "live":       # lista canales de TV en vivo
        for ch in c.live_data().get("channelList", [])[:40]:
            print(ch.get("channelNumber"), ch.get("channelCode"), "|", ch.get("name"))
    elif a == "liveplay":   # liveplay <channelCode>
        print(json.dumps(c.play_live(sys.argv[2]), ensure_ascii=False, indent=2)[:2000])
    else:
        demo(c)
