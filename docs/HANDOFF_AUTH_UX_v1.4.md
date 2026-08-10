# Handoff — Auth/UX + Device Anónimo (magia v1.4.0 → v1.4.6)

Guía para que **otro agente** implemente estos mismos cambios en otro proyecto (un CLI
tipo IPTV portal, o cualquier CLI con login por cuenta + activación de device).

- **Proyecto de referencia:** `magia` (Python CLI). Dos archivos tocados:
  - `iptv_client.py` — cliente HTTP del portal (transporte + endpoints).
  - `magia.py` — CLI interactivo (menús con InquirerPy + rich, flujo de auth).
- Todo lo que sigue va acompañado de la **ubicación exacta** en esos archivos y **snippets**.

---

## 0) Contexto mínimo del sistema (para entender los snippets)

El cliente habla con un "portal IPTV chino". Lo esencial que hay que saber para portar:

- **Transporte** (`iptv_client.IPTVClient.call`): arma un `body` dict, lo cifra
  (`3DES-ECB → base64 → hex`) y hace `POST https://{host}/api/portalCore/{path}`.
  - `call(path, bean, base_fields=True)`:
    - si `base_fields=True` agrega `{portalCode, userId, userToken}` al body.
    - siempre agrega `self.device` (huella de dispositivo, ~16 campos).
    - devuelve el JSON descifrado, o `{"_error": returnCode, "_msg": errorMessage, "_path": path}`
      si `returnCode != 0`, o `{"_exception": ...}` en fallo de red.
- **Sesión**: `self.user_id` + `self.user_token` (efímero, lo emite el server).
- **Device**: `self.device` incluye `sn` (device serial), `drmId`, `deviceToken`,
  `reserve1`. El `sn` viene de `.env` (`IPTV_DEVICE_SN`).
- **`.env`**: config + credenciales opcionales `IPTV_USERNAME` / `IPTV_PASSWORD` (password
  en texto plano; se hashea al enviar con `MD5(password + "cloudstream")`).
- **Helpers del CLI ya existentes**: `t(key)` (i18n EN/ES), `info/warn/error/success`,
  `ask`, `ask_secret`, `confirm`, `select_menu`, `_env_dir()`, `_update_env_var(path, k, v)`.

> **Al portar:** si tu proyecto no cifra el body, ignorá esa parte; lo que importa son los
> **endpoints, los shapes de request, los códigos de error y la lógica de flujo**.

### Endpoints usados (todos `POST /api/portalCore/...`)
| Endpoint | Para qué | Request (bean) |
|---|---|---|
| `v8/active` | activar device (tier free) | `{snToken, authVersion, authCode, preCode, macAddr, reserve1, openNum, channel, matadata, signdata}` + device |
| `v8/login` | login por email | `{accountType:"2", userName, password:MD5(pwd+"cloudstream"), type:"1", macAddr, ...}` |
| `v5/loginOut` | logout server-side | `{userId, userToken}` |
| `v3/snToken` | **mintear device nuevo** | `SnTokenBean` (huella de hardware, ver v1.4.6) |

### Códigos de error relevantes (vienen en `_error` / `_msg`)
| Código | `_msg` (chino) | Significado |
|---|---|---|
| `aaa100082` | `三方账号已经设置密码，只是使用登录方式` | el device está atado a una cuenta con password → usar login |
| `aaa100080` | `snToken已经失效` | snToken inválido (p.ej. SN random no registrado) |

---

## v1.4.0 — Auto-login al arrancar

**Problema:** el prompt "guardar credenciales para auto-login la próxima vez" guardaba
`IPTV_USERNAME/PASSWORD` en `.env`, pero al reabrir el CLI **siempre** mostraba el menú de
auth con "Modo gratuito" como default → quedabas en device free, no en tu cuenta. El
auto-login **nunca estaba implementado**.

**Solución:** al inicio, si hay credenciales guardadas y no se pidió otra cosa, loguear
solo y **saltar el menú**. Escape hatches por flag.

**Ubicación:** `magia.py`, función `main()`, sección `# Auth`.

**Lógica (pseudo-real):**
```python
env_user = os.environ.get("IPTV_USERNAME", "")
env_pass = os.environ.get("IPTV_PASSWORD", "")
force_free = "--free" in sys.argv
force_menu = any(f in sys.argv for f in ("--switch", "--login", "--menu"))

client = None
if force_free:
    ...  # tier free
elif env_user and env_pass and not force_menu:
    # AUTO-LOGIN
    client = IPTVClient(auto_activate=False)
    result = client.login(env_user, env_pass)
    if _is_err(result) or not client.user_id:
        warn(t("relogin_menu")); client = None    # cae al menú
    else:
        client.is_account = True                   # marca sesión de CUENTA (ver v1.4.1)
        success(...); info(t("switch_hint"))

if client is None:
    # ...acá recién se muestra el menú de auth (free/login/register/recover)...
```

**Flags de escape** (documentar en `--help`):
- `--switch` / `--login` / `--menu` → fuerza el menú (cambiar cuenta / registrar / logout).
- `--free` → tier free por una corrida.

**Nota de diseño:** el login del menú manual **siempre pide credenciales frescas** (no
reusa las guardadas), porque solo se llega ahí si no había guardadas, o si el auto-login
falló con las guardadas (reusarlas volvería a fallar).

---

## v1.4.1 — "Cerrar sesión" en el menú principal

**Problema:** el logout estaba solo en el menú de auth; con auto-login ese menú se salta →
nunca se veía (solo quedaba "Salir").

**Solución:** agregar "Cerrar sesión" al **menú principal**, visible solo en sesión de
cuenta. Borra credenciales locales y sale. "Salir" mantiene la sesión (auto-login la próxima).

**Ubicaciones:** `magia.py`
- helper `_clear_saved_creds()`
- marca `client.is_account = True` en cada punto de login-cuenta (auto-login, login manual,
  register, recover).
- construcción del menú principal (índices dinámicos).

**Código:**
```python
def _clear_saved_creds():
    """Borra IPTV_USERNAME/IPTV_PASSWORD del .env y del entorno (logout)."""
    env_path = _env_dir() / ".env"
    if env_path.exists():
        _update_env_var(env_path, "IPTV_USERNAME", "")
        _update_env_var(env_path, "IPTV_PASSWORD", "")
    os.environ.pop("IPTV_USERNAME", None)
    os.environ.pop("IPTV_PASSWORD", None)
```

Menú principal (índices dinámicos para no romper el dispatch existente):
```python
menu = [ ...opciones fijas 0..N... ]
logout_idx = None
if getattr(client, "is_account", False):
    logout_idx = len(menu)
    menu.append((t("logout"), t("logout_hint"), "fg:ansired"))
exit_idx = len(menu)
menu.append((t("exit"), "", "fg:ansired"))

idx = select_menu(t("select"), menu, back=False)
if idx is None or idx == exit_idx:
    break                       # Salir: mantiene la sesión guardada
if logout_idx is not None and idx == logout_idx:
    client.logout()             # (v1.4.2) avisa al server
    _clear_saved_creds()        # olvida credenciales locales
    break
# ...resto del dispatch por índice fijo 0..N...
```

---

## v1.4.2 — Logout server-side (`v5/loginOut`)

**Descubrimiento (decompilando el APK):** el botón de logout del app llama
`POST /api/portalCore/v5/loginOut` con `LogoutBean {userId, userToken}` (fire-and-forget:
ignora la respuesta). Ruta: `n9/ViewOnClickListenerC4544b → ac/m1.m635i → z1.G2 → v5/loginOut`.

**Solución:** método `logout()` en el cliente + llamarlo en el handler de logout **antes**
de borrar credenciales.

**Ubicación:** `iptv_client.py`
```python
def logout(self):
    """v5/loginOut con {userId, userToken}. Fire-and-forget. No-op sin sesión."""
    if not self.user_id or not self.user_token:
        return {"_skipped": "no session"}
    return self.call("v5/loginOut", {"userId": self.user_id, "userToken": self.user_token},
                     base_fields=False)
```
Verificado en vivo: devuelve `{"returnCode": "0", "errorMessage": "成功"}`.

---

## v1.4.3 — Color por opción en los menús

**Problema:** InquirerPy 0.3.4 **no soporta** color por opción — cada opción se dibuja con
una sola clase de estilo (`base/control.py` descarta claves extra del dict; `prompts/list.py`
renderiza el nombre con clase vacía `""`). Emojis "colorean" pero no dejan teñir el texto.

**Solución:** **monkeypatch** de `InquirerPyListControl._get_normal_text` para repintar el
fragmento del nombre según un mapa `nombre → estilo prompt_toolkit`. `select_menu` acepta un
3er elemento opcional `(label, hint, style)`.

**Ubicación:** `magia.py` (arriba de `select_menu`).
```python
_MENU_STYLE = {}   # nombre_mostrado -> estilo prompt_toolkit (ej "fg:ansigreen")

def _install_menu_color_patch():
    try:
        from InquirerPy.prompts.list import InquirerPyListControl
    except Exception:
        return
    if getattr(InquirerPyListControl, "_magia_color_patched", False):
        return
    _orig = InquirerPyListControl._get_normal_text
    def _normal(self, choice):
        frags = _orig(self, choice)
        style = _MENU_STYLE.get(choice.get("name"))
        if not style:
            return frags
        return [(style, txt) if (cls == "" and txt == choice.get("name")) else (cls, txt)
                for (cls, txt) in frags]
    InquirerPyListControl._get_normal_text = _normal
    InquirerPyListControl._magia_color_patched = True
_install_menu_color_patch()

def select_menu(prompt, choices, back=True):
    items = []; _MENU_STYLE.clear()
    for choice in choices:
        label, hint = choice[0], choice[1]
        style = choice[2] if len(choice) > 2 else None
        name = f"{label}  — {hint}" if hint else label
        items.append({"name": name, "value": label})
        if style: _MENU_STYLE[name] = style
    # ...inquirer.select(...).execute(); mapear result→índice por choice[0]...
```
Estilos usados: `"fg:ansigreen"` (playback), `"fg:ansired"` (salir/logout). Solo se colorean
la opción **no** resaltada (la resaltada usa el puntero); alcanza para el efecto.

**Porting (otro menú/lib):** el patrón es genérico → mantené un `dict nombre→estilo` y un
hook de render por-opción. Con `rich`+`prompt_toolkit` propio, aplicá el estilo al armar los
fragmentos. Con otra TUI, buscá el equivalente a "render de cada fila".

---

## v1.4.4 — Glifos Unicode en vez de emojis

**Motivo:** los emojis traen su propio color (no se pueden teñir) y ancho variable. Los
glifos Unicode monocromos del BMP se **tiñen** con el patch de v1.4.3 y los cubren las
fuentes mono estándar (Menlo/SF Mono/Monaco), sin depender de Nerd Fonts (que requieren
fuente instalada por el usuario o dan tofu).

**Cómo elegir glifos con confianza (verificar cobertura):**
```bash
# ¿qué fuentes mono cubren el codepoint U+25B6?
fc-list ":charset=25b6" family | tr ',' '\n' | grep -iE "Menlo|SF ?Mono|Monaco"
```
Descartar los que den vacío (ej: 🔍 U+1F50D, ℹ U+2139, ⏻ U+23FB no están en mono).

**Set final usado** (en los `select_menu` del menú principal + menús de acción):
`⌕` buscar · `✦` recientes · `◆` género · `◷` año · `◍` país · `☺` actor · `★` recomendaciones ·
`▶` play/TV (verde) · `➤` telegram · `?` ayuda · `↓` descargar · `≡` detalles · `↗` enlace ·
`▸` explorar · `⎋` cerrar sesión (rojo) · `✕` salir (rojo).

**Ubicaciones:** los sitios que arman `choices` (menú principal en `main()`, y
`handle_movie`/`handle_series`/`_handle_live_channel`). Ej:
```python
(f"▶ {t('stream_play')}", t("stream_play_hint"), "fg:ansigreen"),   # verde
(f"↓ {t('dl_movie')}",    t("dl_movie_hint")),
```
El emoji/glifo va en el **label** (display); el dispatch sigue siendo por índice, así que no
se rompe nada.

---

## v1.4.5 — Detectar device atado a una cuenta (`aaa100082`)

**Descubrimiento:** una vez que el `sn` del device queda vinculado a una cuenta con
password, `v8/active` (tier free) devuelve `aaa100082` ("usá login"). **Es por SN, no por
IP** (comprobado: misma IP + SN distinto → `aaa100080` distinto). Antes el CLI mostraba un
error genérico ("revisá tu conexión/.env") y salía.

**Solución:** detectar el código y enrutar en consecuencia (en v1.4.6 esto pasa a
"provisionar device nuevo").

**Ubicación:** `magia.py`
```python
def _activate_free():
    """(client|None, status) con status 'ok' | 'linked' (aaa100082) | 'failed'."""
    client = IPTVClient(auto_activate=False)
    r = client.activate()
    if getattr(client, "user_id", ""):
        return client, "ok"
    if isinstance(r, dict) and str(r.get("_error", "")) == "aaa100082":
        return None, "linked"
    return None, "failed"
```
(El `activate()` del cliente ya devuelve el dict `{"_error": "aaa100082", ...}`.)

---

## v1.4.6 — "Volver al anónimo": provisionar un device NUEVO (`v3/snToken`)

**Descubrimiento clave (APK `ac/a1.java`):** el device se **provisiona** con `v3/snToken`,
que **mintea** un `snToken` (UUID). El `sn` local se deriva:
```
sn = MD5(snToken + "ntFT65w6itH!lHCPw7D=@qnsFC5adD28")  # hex minúsculas
```
Luego `v8/active` con ese `sn`+`snToken` da una sesión free nueva. Esto permite "volver al
anónimo" **sin desvincular ni tocar la cuenta** — simplemente se crea un device nuevo.

> **Descartado:** el camino "destructivo" (`unBindEmail` / `v2/unBind`) — esos endpoints
> existen pero el app no los usa (beans muertos), y desvincular sacrifica la cuenta. El
> `v3/snToken` es estrictamente mejor.

**Request `v3/snToken` = `SnTokenBean`** (huella de hardware, todos strings; para un device
nuevo mandar valores frescos/random):
`androidId, board, brand, cpuAbi, cpuId, device, diskInfo, display, etheMac, fingerprint,
gatewayMac, hardware, host, manufacturer, ramSize, romSize, serialNumber, tags, verId, wifiMac`

**Respuesta:** `{snToken, isNew, [sn], [userId]}` (`isNew=="1"` → device nuevo; si el server
no manda `sn`, derivarlo con la fórmula MD5+salt).

**Ubicación:** `iptv_client.py`
```python
import secrets, hashlib
SNTOKEN_SALT = "ntFT65w6itH!lHCPw7D=@qnsFC5adD28"

def new_anonymous_device(self):
    """v3/snToken -> snToken -> sn=MD5(snToken+salt) -> v8/active. No toca ninguna cuenta.
    Al éxito deja self con userId/userToken free y self.device['sn'] nuevo."""
    def _mac(): return ":".join("%02x" % secrets.randbelow(256) for _ in range(6))
    fp = {  # huella nueva (emulador)
        "androidId": secrets.token_hex(8), "board": "goldfish_arm64", "brand": "google",
        "cpuAbi": "arm64-v8a", "cpuId": secrets.token_hex(8), "device": "emu64a",
        "diskInfo": "8GB", "display": "sdk_gphone64_arm64", "etheMac": _mac(),
        "fingerprint": "google/sdk_gphone64_arm64/emu64a:14/UE1A.230829.036/11228894:user/release-keys",
        "gatewayMac": _mac(), "hardware": "ranchu", "host": "abfarm", "manufacturer": "Google",
        "ramSize": "4GB", "romSize": "8GB", "serialNumber": secrets.token_hex(8),
        "tags": "release-keys", "verId": "", "wifiMac": _mac(),
    }
    for k in ("sn", "drmId", "deviceToken", "reserve1"):   # NO mandar el device viejo
        self.device[k] = ""
    r = self.call("v3/snToken", fp, base_fields=False)
    sn_token = r.get("snToken") if isinstance(r, dict) else None
    if not sn_token:
        return {"_error": "snToken_failed", "_detail": r}
    sn = (r.get("sn") or hashlib.md5((sn_token + SNTOKEN_SALT).encode()).hexdigest()).lower()
    self.device["sn"] = sn; self.sn_token = sn_token
    bean = {"snToken": sn_token, "authVersion": "", "authCode": "", "preCode": "",
            "macAddr": "02:00:00:00:00:00", "reserve1": "", "openNum": 4,
            "channel": "default", "matadata": "", "signdata": ""}
    ar = self.call("v8/active", bean, base_fields=False)
    if isinstance(ar, dict) and ar.get("userToken"):
        self.user_id = ar["userId"]; self.user_token = ar["userToken"]
        ar = {**ar, "sn": sn, "snToken": sn_token}
    return ar
```

**Hecho comprobado:** el device nuevo **re-activa con `snToken=""`** y devuelve el **mismo
userId** → es estable. Por eso alcanza con **persistir solo el `sn`** en `.env`
(`IPTV_DEVICE_SN`); el `activate()` normal (snToken="") funciona en las próximas corridas.

**CLI (`magia.py`):**
```python
def _new_anonymous(persist=True):
    c = IPTVClient(auto_activate=False)
    r = c.new_anonymous_device()
    if not (isinstance(r, dict) and r.get("userToken")):
        error(t("provision_failed", msg=_err_msg(r))); return None
    success(...)
    if persist and r.get("sn"):
        _update_env_var(_env_dir()/".env", "IPTV_DEVICE_SN", r["sn"])
        os.environ["IPTV_DEVICE_SN"] = r["sn"]
    return c

def _free_or_login(pf_user="", pf_pass=""):
    c, status = _activate_free()
    if status == "ok":     return c
    if status == "linked": warn(t("device_linked")); return _new_anonymous(persist=True)
    error(t("not_activated")); return None
```
- Flag `--new-device` / `--reset-device` → fuerza `_new_anonymous(persist=True)` (primera
  rama del if/elif de arranque, para que el auto-login no lo pise).
- El "Modo gratuito" del menú y `--free` pasan por `_free_or_login`, así que un device atado
  se auto-resuelve creando uno anónimo nuevo.

---

## Checklist genérico para portar a otro proyecto

1. **Cliente HTTP**: asegurate de tener `login()`, `activate()` y `call(path, bean)` con
   manejo de error `{_error, _msg}`. Agregá `logout()`, `new_anonymous_device()`.
2. **Persistencia** (`.env` o equivalente): `IPTV_USERNAME`, `IPTV_PASSWORD`, `IPTV_DEVICE_SN`
   + helper `set(key, value)` (acá `_update_env_var`) y "borrar" = setear vacío.
3. **Flujo de arranque** (orden if/elif): `--new-device` → `--free` → auto-login → menú.
4. **Marca de sesión**: `client.is_account = True` en logins de cuenta (para mostrar logout).
5. **Menú**: dispatch por índice estable; logout/salir con índices dinámicos al final.
6. **Color** (si tu TUI no lo soporta nativo): mapa `nombre→estilo` + hook de render.
7. **Glifos**: verificá cobertura con `fc-list ":charset=<hex>"` antes de elegir.
8. **Device atado**: detectá el código de "cuenta ya tiene password" y ofrecé/creá device nuevo.

## Apéndice — constantes y secretos (del reversing)
- Salt password login: `"cloudstream"` → `password = MD5(pwd + "cloudstream")` hex-lower.
- Salt derivación de `sn`: `"ntFT65w6itH!lHCPw7D=@qnsFC5adD28"` → `sn = MD5(snToken+salt)` hex-lower.
- `accountType="2"`, `type="1"` en login por email.
- Beans (decompilados): `LogoutBean{userId,userToken}`, `GetFavoritesBean{userToken,userId,queryType,blFlag}`,
  `SnTokenBean{...20 campos de hardware...}`.

## Historial de versiones
`v1.4.0` auto-login · `v1.4.1` logout en menú · `v1.4.2` logout server-side · `v1.4.3`
color por opción · `v1.4.4` glifos Unicode · `v1.4.5` detectar device atado · `v1.4.6`
volver al anónimo (device nuevo via v3/snToken).
