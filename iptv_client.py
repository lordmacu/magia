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
import hashlib
import json
import os
import secrets
import sys
import requests
from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad, unpad
from pathlib import Path

# Salt para derivar el `sn` local a partir del snToken (v3/snToken -> device nuevo).
# Descubierto en el APK (ac/a1.java): sn = MD5(snToken + SNTOKEN_SALT) en hex minúsculas.
SNTOKEN_SALT = "ntFT65w6itH!lHCPw7D=@qnsFC5adD28"

requests.packages.urllib3.disable_warnings()

# ─────────────────────────────  .env loader  ─────────────────────────────
def _find_env():
    cwd = Path.cwd() / ".env"
    if cwd.exists():
        return cwd
    home_magia = Path.home() / ".magia" / ".env"
    if home_magia.exists():
        return home_magia
    script = Path(__file__).parent / ".env"
    if script.exists():
        return script
    return None

def _load_dotenv():
    env_path = _find_env()
    if not env_path:
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
        # Como renovar la sesion si el server la declara muerta (ver call/_reauth).
        self._auth_mode = "manual" if user_token else None
        self._creds = None
        self._reauthing = False
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
    # Codigos con los que el server declara la sesion muerta: aaa100028 = "未登录！"
    # (no logueado), aaa100027 su hermano. La app NO refresca token -- marca la
    # sesion invalida y abre el dialogo de login
    # (com/module/basemvp/AbstractActivityC2036a.U5, ac/f1). Tampoco hay heartbeat.
    # Aqui re-minteamos con las mismas credenciales y reintentamos una vez, para que
    # el CLI no haya que reiniciarlo despues de quedarse idle.
    SESSION_DEAD = ("aaa100027", "aaa100028")
    # aaa100083 = "您的账号已经在其他设备登录" (la cuenta ya inicio sesion en otro dispositivo).
    # La app lo mete en la MISMA rama de sesion invalida que 100027/28 (ac/f1.java:142).
    # En device/free re-activar es inofensivo y equivale a reiniciar el CLI, que es lo que
    # destraba el caso real. Con una cuenta de verdad NO se re-loguea solo: seria pelearse
    # la sesion a ida y vuelta con el dispositivo del usuario.
    SESSION_TAKEN = ("aaa100083",)
    # Rutas que establecen sesion (o la cierran): reintentar con re-auth ahi no tiene
    # sentido y en v3/snToken seria danino (corre con el device a medio limpiar).
    NO_REAUTH_PATHS = ("v8/active", "v8/login", "v5/loginOut", "v3/snToken")

    def call(self, path, bean=None, base_fields=True):
        r = self._call_once(path, bean, base_fields)
        if (isinstance(r, dict)
                and not self._reauthing
                and not any(path.startswith(p) for p in self.NO_REAUTH_PATHS)):
            code = str(r.get("_error", ""))
            recuperable = (code in self.SESSION_DEAD
                           or (code in self.SESSION_TAKEN and self._auth_mode == "device"))
            if recuperable and self._reauth():
                r = self._call_once(path, bean, base_fields)
        return r

    def _reauth(self):
        """Re-mintea la sesion por la misma via con que se obtuvo.

        'account' -> v8/login con las credenciales guardadas; 'device' -> v8/active.
        'manual' (use_account con un token capturado) no se puede renovar: activar
        ahi degradaria una sesion de cuenta a free en silencio, asi que se rinde."""
        self._reauthing = True
        try:
            if self._auth_mode == "account" and self._creds:
                r = self.login(*self._creds)
            elif self._auth_mode == "device":
                r = self.activate()
            else:
                return False
        finally:
            self._reauthing = False
        return bool(isinstance(r, dict) and r.get("userToken"))

    def _call_once(self, path, bean=None, base_fields=True):
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
            self._auth_mode = "device"
        return r

    def use_account(self, user_id, user_token):
        """Fija una sesión de CUENTA ya logueada (obtenida con login manual + captura del token)."""
        self.user_id = user_id; self.user_token = user_token
        self._auth_mode = "manual"; return self

    def login(self, username, password, account_type="2", type_="1", area_code=""):
        """Login por cuenta email.  accountType='2', type='1' (login por email).

        El campo `password` que viaja es MD5(password) en HEX minúsculas (32 chars),
        dentro del body 3DES normal.  Confirmado con Frida (oráculo sobre fc.b.b,
        el DESede/ECB/PKCS5 del body): el app envía p.ej.
          {"accountType":"2","userName":"...","password":"049ec44fd8dd354dee...", ...}
        y ese valor es MD5 hex (k2.i.a = MessageDigest MD5 -> hex).  El getter
        cc.m0.m6123x() devuelve ese hash ya guardado (user_password_new, sin cifrar
        extra), y LoginBean -> json -> fc.b.b() = mismo encrypt_body de siempre.
        Las llaves DES de AbstractC1235i ('==RiXVKU'/'dCsPLwiy') NO son de la red.
        matadata/signdata van vacíos (solo STB con /system/etc/.UCERT los llevan).

        `password` se recibe en claro y se hashea aquí.
        HASH REAL (verificado en vivo 2026-08): MD5(password + "cloudstream") en hex minúsculas.
        El salt "cloudstream" es fijo (decompilado: `AbstractC5729e.m22190c` hace
        `MD5((str + "cloudstream").getBytes())`, getBytes()=UTF-8).  El comentario viejo decía
        "MD5 plano latin-1" y estaba MAL — por eso el login fallaba con credenciales correctas."""
        creds = (username, password, account_type, type_, area_code)
        password = hashlib.md5(((password or "") + "cloudstream").encode("utf-8")).hexdigest()
        bean = {"accountType": account_type, "userName": username, "password": password, "type": type_,
                "macAddr": "02:00:00:00:00:00", "areaCode": area_code, "verificationCode": "",
                "verificationToken": "", "matadata": "", "signdata": "", "channel": "default"}
        r = self.call("v8/login", bean, base_fields=False)
        if isinstance(r, dict) and r.get("userToken"):
            self.user_id = r["userId"]; self.user_token = r["userToken"]
            self._auth_mode = "account"; self._creds = creds
        return r

    def logout(self):
        """Cierra sesion en el SERVER (v5/loginOut). Replica LogoutBean{userId, userToken}
        del app (fire-and-forget: el app descarta el resultado). Invalida el userToken en el
        backend; NO borra credenciales locales (de eso se encarga el CLI). No-op sin sesion.
        Ruta decompilada: n9/ViewOnClickListenerC4544b -> ac/m1.m635i -> z1.G2 -> v5/loginOut."""
        if not self.user_id or not self.user_token:
            return {"_skipped": "no session"}
        return self.call("v5/loginOut", {"userId": self.user_id, "userToken": self.user_token},
                         base_fields=False)

    # ─────────────  DEVICE ANÓNIMO NUEVO (volver al modo free)  ─────────────
    def new_anonymous_device(self):
        """Provisiona un device ANÓNIMO nuevo y lo activa en tier free, SIN tocar ninguna cuenta.
        Flujo (descubierto en el APK, ac/a1.java): v3/snToken -> snToken -> sn = MD5(snToken+salt)
        -> v8/active.  Sirve para 'volver al anónimo' cuando el device viejo quedó atado a una
        cuenta con password (v8/active -> aaa100082).  Al éxito deja self con userId/userToken free
        y setea self.device['sn'] + self.sn_token (para persistir en .env si se quiere).
        Devuelve la respuesta de active (con {sn, snToken} agregados) o un dict de error."""
        def _mac():
            return ":".join("%02x" % secrets.randbelow(256) for _ in range(6))
        fp = {
            "androidId": secrets.token_hex(8), "board": "goldfish_arm64", "brand": "google",
            "cpuAbi": "arm64-v8a", "cpuId": secrets.token_hex(8), "device": "emu64a",
            "diskInfo": "8GB", "display": "sdk_gphone64_arm64", "etheMac": _mac(),
            "fingerprint": "google/sdk_gphone64_arm64/emu64a:14/UE1A.230829.036/11228894:user/release-keys",
            "gatewayMac": _mac(), "hardware": "ranchu", "host": "abfarm", "manufacturer": "Google",
            "ramSize": "4GB", "romSize": "8GB", "serialNumber": secrets.token_hex(8),
            "tags": "release-keys", "verId": "", "wifiMac": _mac(),
        }
        # pedir snToken con una huella nueva y SIN mandar el device viejo
        for k in ("sn", "drmId", "deviceToken", "reserve1"):
            self.device[k] = ""
        r = self.call("v3/snToken", fp, base_fields=False)
        sn_token = r.get("snToken") if isinstance(r, dict) else None
        if not sn_token:
            return {"_error": "snToken_failed", "_detail": r}
        sn = (r.get("sn") or hashlib.md5((sn_token + SNTOKEN_SALT).encode()).hexdigest()).lower()
        self.device["sn"] = sn
        self.sn_token = sn_token
        bean = {"snToken": sn_token, "authVersion": "", "authCode": "", "preCode": "",
                "macAddr": "02:00:00:00:00:00", "reserve1": "", "openNum": 4,
                "channel": "default", "matadata": "", "signdata": ""}
        ar = self.call("v8/active", bean, base_fields=False)
        if isinstance(ar, dict) and ar.get("userToken"):
            self.user_id = ar["userId"]
            self.user_token = ar["userToken"]
            self.jwt = ar.get("jwtToken", "")
            self._auth_mode = "device"     # el device nuevo ya puede auto-renovarse
            ar = {**ar, "sn": sn, "snToken": sn_token}
        return ar

    # ─────────────  REGISTRO / RECUPERAR CONTRASEÑA (email + código)  ─────────────
    @staticmethod
    def _hash_pwd(password):
        """Hash del password que espera el server: MD5(password + 'cloudstream') hex-lower.
        (salt fijo del app, AbstractC5729e.m22190c; getBytes()=UTF-8). Verificado en vivo."""
        return hashlib.md5(((password or "") + "cloudstream").encode("utf-8")).hexdigest()

    def send_email_verify_code(self, email, type_="1"):
        """Envía un código de verificación al `email`.  type: '1'=registro/bind email, '3'=reset password.
        No requiere estar logueado, pero conviene tener una cuenta de device (activate) para userId/userToken."""
        bean = {"email": email, "type": type_, "userId": self.user_id, "userToken": self.user_token}
        return self.call("v2/sendEmailVerifyCode", bean, base_fields=False)

    def validate_verify_code(self, email, code, type_="1"):
        """Valida el código recibido (v2/validateVerifyCode).  Usa VerifyEmailCodeBean
        (campos exactos del app: type, email, verifyCode, userToken, userId — NO phone/
        verificationCode/password; ese era el bug '请求参数异常').  Devuelve VerifyEmailCodeResult.
        Ruta decompilada: register C4596a -> D0 -> z1.q3 -> r0 = v2/validateVerifyCode."""
        bean = {"type": type_, "email": email, "verifyCode": code,
                "userToken": self.user_token, "userId": self.user_id}
        return self.call("v2/validateVerifyCode", bean, base_fields=False)

    def bind_email(self, email, password, type_="1"):
        """REGISTRO: asocia `email` + `password` a la cuenta (v2/bindEmail).  password en claro
        (se hashea con el salt cloudstream).  Llamar validate_verify_code() antes con el código."""
        bean = {"email": email, "pwd": self._hash_pwd(password), "type": type_,
                "userId": self.user_id, "userToken": self.user_token}
        return self.call("v2/bindEmail", bean, base_fields=False)

    def reset_pwd(self, email, new_password, verify_code, type_="3"):
        """RECUPERAR/RESETEAR contraseña (v4/resetPwd).  `new_password` en claro (se hashea).
        `verify_code` = el código que llegó al email (enviado con send_email_verify_code(type='3'))."""
        bean = {"type": type_, "email": email, "password": self._hash_pwd(new_password),
                "verifyCode": verify_code, "userToken": self.user_token, "userId": self.user_id}
        return self.call("v4/resetPwd", bean, base_fields=False)

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

    # ─────────────  FAVORITOS / SEGUIDOS / USUARIO  ─────────────
    def favorites(self, query_type="all", bl_flag="0"):
        """FAVORITOS del usuario (getFavorite). Devuelve favoriteList[] con metadata rica
        (contentId, name, type, director, score, updateCount, posterList...). Requiere sesion."""
        return self.call("getFavorite", {"queryType": query_type, "blFlag": bl_flag})

    def add_favorite(self, content_ids, type_="1", bl_flag="0"):
        return self.call("v2/addFavorite", {"contentIdList": content_ids, "type": type_, "blFlag": bl_flag})

    def del_favorite(self, content_ids):
        """Quita favoritos (delFavorite). `content_ids` = lista de contentId."""
        return self.call("delFavorite", {"list": content_ids})

    def subscribe_list(self, type_=""):
        """SERIES/PELICULAS QUE EL USUARIO SIGUE (getSubscribe, 追剧).  Es lo mas cercano a
        'lo que el usuario ha estado viendo': el portal NO expone historial de reproduccion
        (el progreso se guarda local en el device), pero SI la lista de seguidos.
        Devuelve subscribeList[] = {subscribeId, contentId, name, type, contentType, score,
        updateCount, volumnCount, updateTime, posterList[]}.  `type_`='' = todos.  Requiere sesion."""
        return self.call("getSubscribe", {"type": type_})

    def add_subscribe(self, content_id, type_="1"):
        """Sigue (追剧) un contenido (addSubscribe)."""
        return self.call("addSubscribe", {"type": type_, "contentId": content_id})

    def del_subscribe(self, content_ids):
        """Deja de seguir (delSubscribe). `content_ids` = lista de contentId."""
        return self.call("delSubscribe", {"list": content_ids})

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
