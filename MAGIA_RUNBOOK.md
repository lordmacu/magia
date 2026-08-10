# MAGIA — Runbook técnico completo: TV en vivo (y VOD) 100% Python de Magis TV

> **Propósito.** Documento autocontenido y reproducible. Explica EXACTAMENTE cómo funciona el
> streaming de Magis TV / Xuper Hydra (`com.xuper.netxxus`, lib nativa `libranger-jni.so`) sin la
> app ni adb en runtime, **el camino correcto**, y **cómo re-obtener cada valor / clave** si el
> proveedor los cambia. Un agente futuro debería poder rehacer todo con esto.
>
> Dispositivo/proyecto propios del usuario (interop/seguridad, autorizado). Última verificación:
> **2026-08-09**. Repo: `lordmacu/magia` en `/Users/cristian/magia`.

---

## 0. TL;DR — el camino correcto

**El vivo se sirve por el CDN Cloudflare (`sign_type=cfl`) DIRECTO, igual que las películas (VOD).
NO necesita el redirect `/slb` a `nvuos`, ni el cripto "Función A", ni el transporte P2SP.**

```
play_live(channel)            → Content-License (token de licencia del canal)
get_slb(merge, [channel])     → entrada CDN tag=live, sign_type=cfl: host + Content-Auth(url)
GET http://<cflhost>/live/<channel>.m3u8   [headers: Content-Auth, Content-License, UA Ranger]
  → playlist HLS con URLs ABSOLUTAS de segmentos en hosts CDN variables
GET http://<seghost>/live/<channel>/<channel>_shisui_<ts>.ts
  [Content-Auth + &sign2_method=sign_o3&instance=0&start_moment=<ms>&sign2=<sign_o3(token,ms)>]
  → 200 + MPEG-TS (primer byte 0x47)
```

Implementación lista: **`live_cfl.py`** (proxy HLS local que re-firma cada segmento con `sign_o3`).
```bash
python3 live_cfl.py <channel_code> --play      # abre en mpv/VLC
```

La ruta P2SP (`/slb` → `nvuos` → `149.34.241.153:8119`) y el cripto "Función A/B" están documentados
en §6 como **material de referencia / plan B**, pero **no hacen falta para streamear**.

---

## 1. Entorno y herramientas (lo que hace falta)

- **App / target:** `com.xuper.netxxus` (Xuper Hydra / Magis TV). Lib: `lib/arm64-v8a/libranger-jni.so`
  (ARM64, OLLVM). APK en `/Users/cristian/mago/Xuper.Hydra.HDR.4KP.apk`.
- **Device de RE:** emulador `emulator-5554` rooteado (`adb -s emulator-5554 root`).
  - ⚠️ `frida.get_usb_device()` puede agarrar el **teléfono real** ("SM S926B", 192.168.1.21) →
    **usar SIEMPRE `frida.get_device('emulator-5554')`** o `adb -s emulator-5554`.
  - frida-server en el emu: `/data/local/tmp/frida-server` (reiniciar si se cuelga:
    `adb -s emulator-5554 shell "su 0 sh -c 'pkill -9 frida-server; cd /data/local/tmp && ./frida-server &'"`).
- **Python:**
  - Frida requiere **py3.14**: `/opt/homebrew/opt/python@3.14/bin/python3.14` (tiene `frida`).
  - Cliente API / crypto / Unicorn: `/opt/homebrew/bin/python3` (tiene `pycryptodome`, `requests`,
    `unicorn`, `python-dotenv`).
- **Ghidra 12.1.2 headless** + `openjdk@21` (para RE del cripto; ver §7).
- **radare2** (`r2`) para disassembly rápido.
- **tcpdump** (en el emu, vía adb root) para descubrir URLs de media reales.
- **`.env`** (en el repo, gitignoreado) con credenciales IPTV. El cliente `IPTVClient()` se
  auto-activa por device SN. Variables: `IPTV_APP_ID`, `IPTV_APK_VERSION`, `IPTV_DEVICE_SN`,
  `IPTV_DEVICE_TOKEN`, `IPTV_DEVICE_RESERVE1`, `IPTV_DEVICE_DRM_ID`.

Archivos clave del repo:
- `iptv_client.py` — cliente de la API del portal (activate, play_live, get_slb, live_data, ...).
- `sign_o3.py` — genera el `sign2` (emula la compresión MD5-tweak con Unicorn). **Necesita el .so**
  (`libranger-jni.so` junto al módulo, o env `LIBRANGER_SO=/ruta`).
- `live_cfl.py` — **el streamer de vivo (camino correcto)**.
- `download_iptv.py` — descarga VOD (mismo patrón cfl; sirve de referencia).
- `svs_cipher.py` — cripto SVS Función A/B (plan B, §6).
- `svs_client.py` — redirect SVS/P2SP (plan B, §6, no funciona end-to-end por muro de red).
- `so_emulator.py` — toolkit para emular funciones nativas ARM64 (mapea ELF + relocs; helpers
  `trace_calls`/`watch_reads`/`capture_at`). Base de `sign_o3.py`; útil para re-emular cualquier fn.
- `aes_mbed.py` — AES estilo mbedTLS en Python (equivalent-inverse-cipher, self-tested 128/256).
  Se usó durante el RE para validar el cipher SVS; `svs_cipher.py` ya usa `pycryptodome`.
- `frida/*.py`, `ghidra_scripts/*.java` — herramientas de RE (§7).

---

## 2. CAMINO CORRECTO — paso a paso, con cómo obtener CADA valor

### Paso 0 — Cliente e identidad
```python
from dotenv import load_dotenv; load_dotenv()
from iptv_client import IPTVClient
client = IPTVClient()          # lee .env, se auto-activa (activate) por device SN
```
- **Cómo obtener las credenciales del `.env`** si cambian: son del dispositivo/cuenta del usuario.
  `IPTVClient.activate()` las usa para obtener `user_id`/`user_token`. Si la sesión expira, el cliente
  re-activa solo (ver `download_iptv.py`: reintenta `activate()` ante error `100083`/token).

### Paso 1 — Listar canales en vivo → `channel_code`
```python
ld = client.live_data(column_id=76182, size=500)   # 76182 = "All Channels"
canales = ld["channelList"]                          # cada uno: {channelCode, name, ...}
channel_code = canales[0]["channelCode"]             # ej: "cyx_50fdcc0817d61_720p"
```
- **Otras categorías** (`column_id`): 76206 Deportes, 87034 Vivo gratis, 76205 Cine y Series,
  77970 Más popular, 76189 24/7. La lista completa: `client.live_categories()["recommendList"]`.
- El `channel_code` es el identificador del canal (también = `media_code` = `playCode`).

### Paso 2 — `play_live` → Content-License
```python
pl = client.play_live(channel_code)                  # call a "v4/startPlayLive"
addr = pl["liveAddressList"][0]
content_license = addr["license"]                    # el header Content-License
# playCode == channel_code ; AVFormat == "ts"
```
- **Estructura de `license`** (querystring): `app_id=...&tag=free&scheme=md5-01&media_code=<channel>&
  expired=<epoch>&token=<32HEX>`. El `token` de la license NO es el de sign_o3 (ese sale del cfl url).

### Paso 3 — `get_slb` → CDN `cfl` (Cloudflare) + Content-Auth
```python
slb = client.get_slb(type_="merge", live_codes=[channel_code])   # "v14/getSlbInfo"
for cdn in slb["cdn_list"]:
    if cdn["tag"] != "live": continue
    for u in cdn["url_list"]:
        url = u["url"]
        if "sign_type=cfl" in url:                   # ← la entrada Cloudflare directa
            cfl_host = cdn["main_addr"].replace("http://","").split("/")[0]  # ej niguof.vynbszicd.com
            cfl_auth = url                            # ← el Content-Auth base (querystring)
            token   = re.search(r"token=([0-9A-Fa-f]{32})", url).group(1)    # UPPERCASE
```
- `get_slb` devuelve VARIAS entradas por canal. Para el vivo importan:
  - `tag=live, sign_type=cfl` → **Cloudflare directo (ESTA es la que se usa)**. Hosts vistos:
    `niguof.vynbszicd.com`, `aluve.rdgqkfxio.com` (fast-flux, rotan; siempre re-leer de get_slb).
  - `tag=live, sign_type=cs` → iCDN/P2SP (nvuos), la ruta alternativa que NO usamos (§6).
  - `tag=live, sign_type=goog` → CDN Google (otra alternativa).
- **El campo `url`** ES el Content-Auth base (con `dev_id, user_id, main_addr, sign_type=cfl, link=cf,
  session_id, client_ip, auth_id, expired, tag, check_play_ip, token`). NO trae sign2 todavía.
- **`cfl_host` cambia seguido** (Cloudflare fast-flux) y `expired` caduca (~horas): **siempre re-llamar
  get_slb** por sesión; nunca hardcodear el host ni el auth.

### Paso 4 — Playlist m3u8
```python
H = {"Content-Auth": cfl_auth, "Content-License": content_license,
     "User-Agent": "Ranger/4.9.4-17294ac0",
     "App": "com.android.msandroid", "App-Version": "49902"}
m3u8 = requests.get(f"http://{cfl_host}/live/{channel_code}.m3u8", headers=H).text
```
- **El path `/live/<channel>.m3u8`** se descubrió por **tcpdump** del tráfico real del app (§7.3).
  Es HTTP plano (puerto 80) aunque el host esté tras Cloudflare.
- El m3u8 trae **URLs ABSOLUTAS** de segmentos, en hosts CDN distintos y variables:
  `http://<seghost>/live/<channel>/<channel>_shisui_<timestamp>.ts` (hosts: tdgao/nmbde/...).
- Tiene tags custom (`#EXT-SEGMENT:<byteranges>/rd=<ts>`) que un player estándar ignora.

### Paso 5 — Segmentos `.ts` con `sign2` fresco (sign_o3)
```python
from sign_o3 import sign_o3, now_moment_ms
mom = now_moment_ms()                                  # start_moment en ms (fresco POR request)
s2  = sign_o3(token, mom)                               # ← el sign2 (32 hex lowercase)
auth_seg = f"{cfl_auth}&sign2_method=sign_o3&instance=0&start_moment={mom}&sign2={s2}"
Hs = {**H, "Content-Auth": auth_seg, "X-Buffer": "0"}   # opcional Ranger-Id (no obligatorio)
ts = requests.get(seg_url, headers=Hs).content          # 200, primer byte 0x47 (MPEG-TS)
```
- **Cada segmento necesita un `sign2` NUEVO** (depende de `start_moment` = ahora en ms). Reusar uno
  viejo → 401.
- **Los segmentos en vivo EXPIRAN en segundos**: siempre re-fetchear el m3u8 fresco y pedir los
  segmentos NUEVOS al instante. (Por eso el proxy re-fetchea el m3u8 en cada request del player.)
- `token` = el del `cfl_auth` (UPPERCASE). `sign_o3(token, mom)` construye el mensaje
  `token=<token>&sign2_method=sign_o3&instance=0&start_moment=<mom>` + SALT y lo hashea (§5).

### Paso 6 — Reproducir (proxy HLS local)
`live_cfl.py` levanta un proxy en `127.0.0.1:<port>` que:
1. sirve `/play.m3u8` → re-fetchea el m3u8 del cfl_host y reescribe cada URL de segmento a
   `http://127.0.0.1:<port>/seg?u=<urlencoded>`.
2. sirve `/seg?u=...` → baja el segmento con un `Content-Auth` re-firmado con sign_o3 fresco.
```bash
python3 live_cfl.py cyx_50fdcc0817d61_720p --play
```
Verificado 2026-08-09: m3u8 → 200; 6/6 segmentos → 200 + TS válido (0x47).

**Integrado en el CLI (`magia.py`):** el menú `Live TV → [categoría] → [canal] → "Stream"` ahora
llama a `live_cfl.resolve_live_cfl()` + `live_cfl.start_proxy()` y abre el proxy en mpv/VLC/IINA
(igual que películas/series). `stream_live()` fue reescrito para usar el CDN cfl (antes usaba el
`get_live_cdn_auth`/redirect P2SP que fallaba). `get_live_cdn_auth` y `live_stream.py` quedan como
referencia del camino P2SP.

---

## 3. Comparación con VOD (películas/series) — de dónde salió la pista

`download_iptv.py` ya bajaba películas por el mismo patrón:
```
play_vod(contentId) → license + media_code
get_slb() → entrada tag=vod, sign_type=cfl → cdn_base
GET {cdn_base}/vod/{media_code}_media.mp4   [Content-Auth, Content-License, UA Ranger]
```
El vivo es idéntico salvo: `tag=live`, path `/live/{channel}.m3u8` + segmentos `.ts`, y los segmentos
requieren `sign2` (sign_o3) fresco (el VOD, al ser un archivo, no lo necesitó). **La pista clave fue
"probar lo que hicimos con las películas".**

---

## 4. Valores actuales (2026-08-09) y cómo re-derivarlos

| Valor | Actual | De dónde sale / cómo re-obtenerlo si cambia |
|---|---|---|
| `channel_code` | p.ej. `cyx_50fdcc0817d61_720p` | `live_data(76182).channelList[].channelCode` |
| `content_license` | dinámico/sesión | `play_live(channel).liveAddressList[0].license` |
| `cfl_host` | `niguof.vynbszicd.com` / `aluve.rdgqkfxio.com` | `get_slb().cdn_list[tag=live, sign_type=cfl].main_addr` (rota; re-leer siempre) |
| `cfl_auth` (Content-Auth) | dinámico/sesión | el campo `url` de esa misma entrada |
| `token` (para sign2) | 32-HEX UPPER, por sesión | `token=` del `cfl_auth` |
| path m3u8 | `/live/<channel>.m3u8` | descubierto por tcpdump (§7.3); estable |
| headers | `App`, `App-Version`, `User-Agent: Ranger/4.9.4-17294ac0`, `Content-Auth`, `Content-License` | captura del request real (§7.3) |
| `sign2` | por request | `sign_o3(token, start_moment_ms)` (§5) |

**Todo lo del vivo es dinámico (viene de la API por sesión), salvo la fórmula de `sign_o3`.**
Si el streaming deja de andar, el sospechoso #1 es `sign_o3` (§5) o headers/paths (§7.3).

---

## 5. `sign_o3` — la firma de segmentos (lo único "cripto" del camino correcto)

### Fórmula (verificada 5/5 en vivo)
```
SALT  = b"salt3333=4" + bytes.fromhex("980d0a1532c9c3821708c0")     # constante global
msg   = f"token={TOKEN}&sign2_method=sign_o3&instance=0&start_moment={MOMENT}".encode() + SALT
sign2 = tweaked_md5(msg)                                            # 32 hex lowercase
```
- `tweaked_md5` = un MD5 **modificado** (mismo IV/K/shifts/padding que MD5 estándar, pero con el
  *message schedule* cambiado). No se reimplementa a mano: **`sign_o3.py` EMULA la función de
  compresión real del `.so` con Unicorn** (fcn `0x529178`). Igual de exacto y robusto.
- `TOKEN` = el `token` del Content-Auth (del cfl url). `MOMENT` = `int(time.time()*1000)` fresco.

### Cómo re-extraer `sign_o3` si cambia (el SALT, la fórmula o el schedule)
1. **SALT / estructura del mensaje:** hookear `MD5_Update` de la "impl-B" (`update=0x529044`) con Frida
   y **unir los chunks** → el mensaje exacto que se hashea. Ahí se ve el `salt3333=4` + 11 bytes
   binarios. Alternativa: `strings`/RE del binario. (Ver `SIGN_O3_CRACK.md` para el histórico.)
2. **Compresión (por si cambia el schedule):** re-emular `0x529178` con `so_emulator.py`/Unicorn
   (mapear ELF + relocs `R_AARCH64_RELATIVE`/`DT_RELR`, escribir state16+block64, `emu_start`). El
   offset `0x529178` se ubica buscando la tabla de senos de MD5 (`0xd76aa478…`) en el binario.
3. **Verificar:** hookear el `write()`/ssl de la app, capturar `(token, start_moment, sign2)` reales
   y comparar con `sign_o3(token, start_moment)`.

Detalle completo del crack de sign_o3: `SIGN_O3_CRACK.md`.

---

## 6. PLAN B / referencia — la ruta P2SP (`/slb` → nvuos) y el cripto SVS (Función A/B)

**No hace falta para el vivo** (§0), pero está resuelto y documentado por si se necesita el endpoint
P2SP `149.34.241.153:8119` (token lowercase + trans_id) en el futuro.

### 6.1 El flujo P2SP
```
get_slb(live) → entrada tag=live, sign_type=cs, main_addr=nvuos.7r03dh6rph.com, campo url = querystring
Función A: auth= = base64_REQUEST( AES-128-CBC( querystring_sin_cdn_type, key, iv ) )
GET https://nvuos.7r03dh6rph.com/slb/v9/live?auth=<auth>
Función B: descifra la respuesta → {"servers":[{"media_url":"http://149.34.241.153:8119/live/?...
           &token=<lowercase>&trans_id=..."}]}
```
⚠️ **Muro de RED (no cripto):** nvuos está tras Cloudflare; el origin devuelve **401** a un `auth=`
fresco y **503** al replay verbatim del request EXACTO del app. Ni el request del app funciona
replayeado desde la Mac → binding server-side (token single-use / sesión / TLS-fingerprint del cliente
Ranger). Por eso se abandonó en favor del camino cfl. (El crypto en sí quedó 100% correcto.)

**Pistas ya descartadas** (para no repetirlas): la IP pública del Mac == `client_ip` del querystring
(186.81.59.70) → no es filtro por IP; llamar `play_live` ANTES de `get_slb` NO cambia el 401;
cambiar/quitar `Ranger-Id` no cambia nada; con `cdn_type` en el querystring → 503, sin él → 401
(o sea sin `cdn_type` SÍ llega al auth-check del server).

**Si algún día se quiere romper el muro** (orden sugerido, del svs_client.py):
1. Capturar el **request + la RESPONSE** del app en el mismo spawn (hook al lado `ssl_read`, análogo
   al `memcpy@0x71b4c0` de ssl_write) para ver qué recibe realmente el app tras el `GET /slb` — puede
   que el 200 traiga algo que el replay no reproduce, o que el token sea de un solo uso.
2. RE del **flujo de sesión/token**: ver si el `/slb` valida el token contra un estado creado por otra
   llamada previa de la app (handshake star/P2SP `xsvs.vfltbr.com:18084`), no sólo por el `auth=`.
3. **TLS/JA3 fingerprint** del cliente Ranger (mbedTLS estático): Cloudflare puede estar filtrando por
   fingerprint → replicar el ClientHello de Ranger (curl-impersonate / utls) en vez de `requests`.
Nada de esto es cripto (eso ya está resuelto); es red/sesión/transporte.

### 6.2 Función A — cifrar el `auth=` (CRACKEADA y verificada)
```python
# svs_cipher.py:
from svs_cipher import encrypt_svs_request       # querystring -> auth=
auth = encrypt_svs_request(querystring)          # querystring = get_slb url iCDN SIN "cdn_type="
```
```
auth= = base64_REQUEST( AES-128-CBC( querystring, key, iv, PKCS7 ) )
key = d5b1d91ce63c381f339f45f2d932aa50           (FIJO)
iv  = 19aecdc893ab2aee4dd10e5928f9716f           (FIJO)
alfabeto REQUEST = jWB7YtC3n9iXbEkUcJl1VxF4STpQoOIaRmh2M-efAgLwPqGr6uyD5vNsdH_Kz0Z8   (≠ el de la respuesta)
```
- **El "muro" de meses era ese ALFABETO base64 distinto para el request** (se decodificaba con el
  estándar → basura → falsa idea de "clave inexistente / cipher inlined / CFB"). Es CBC plano.
- El querystring que se cifra = el `url` de la entrada iCDN (`sign_type=cs`) de get_slb, **quitando
  `cdn_type`**. El orden de campos no importa (el server parsea por nombre).

**Cómo re-extraer key/iv/alfabeto de Función A si cambian:**
- **key + iv:** hook con Frida al wrapper de encrypt **`0x678b14`** (firma:
  `enc(x0=keyHex std::string, x1=ivHex std::string, x2=pt char*, x3=len, x4=out, x5=outlen)`).
  Leer x0/x1 como `std::string` de libc++ (§7.4). Filtrar el call cuyo pt es el querystring
  (`main_addr`/`spared_addr`/`sign_type=cs`, len ~380-520). El key sale `d5b1d91c…`.
  Script: `frida/svs_authkey3.py` / `frida/svs_allenc.py` (install temprano por dlopen).
  Alternativa: hook `0x2ff160` (`FUN_003ff160`, el ÚNICO método encrypt→auth=): retorno std::string
  en **x8**, transport en x0, plaintext en x1; **key = std::string en [x0+8]** (script `frida/svs_ff160b.py`).
- **alfabeto REQUEST:** leer en runtime `module_base + 0x76cab0` (64 bytes) — está deobfuscado (una
  rutina XOR al inicio de `FUN_003ff160` lo desofusca; en el binario estático es `.bss`=0xff). Los 12
  bytes previos (`0x76caa4`) son el marcador `"req:"`. Frida:
  `asc(Process.findModuleByName("libranger-jni.so").base.add(0x76cab0), 64)`.
  Para HALLAR ese offset si se mueve: Ghidra decompila `FUN_003ff160`; llama
  `FUN_004086ac(&DAT_0086cab0, ct, len, out, outlen)` = el encoder base64; `DAT_0086cab0` (addr Ghidra)
  − `0x100000` = el vaddr a leer en runtime (0x76cab0).

### 6.3 Función B — descifrar la respuesta SVS (CRACKEADA y verificada)
```python
from svs_cipher import decrypt_svs_response
servers = json.loads(decrypt_svs_response(body, kind="servers"))
```
```
respuesta = base64_STANDARD → [4-byte header BE = payload_len][AES-128-CBC ct] → PKCS7
kind="servers": key=d5b1d91ce63c381f339f45f2d932aa50  iv=e130e2320d394a7afab21f1b5a1c8251
kind="auth"   : key=e9ef5394581f7551346dab732a88507f  iv=71e9775c089d8be699fd850148345231
alfabeto RESPUESTA (estándar Ranger) = B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7
```
**Cómo re-extraer las claves de Función B:** hook al wrapper de decrypt **`0x678cf0`**
(`dec(keyHex, ivHex, in, len, out, outlen)`), leer x0/x1 como std::string. El call que descifra la
respuesta de servers (key `d5b1d91c`, ~512B) da la clave. Script base: `frida/svs_bt_decrypt.py`,
`frida/svs_crypto.py`.

### 6.4 Todas las claves son MD5 de literales (nota)
Las claves (`d5b1d91c`, `e9ef5394`, `e9f663ff`, …) son el **MD5 raw (16B) de un literal** del binario,
pasadas como hex-string de 32 chars y hex-decodeadas por `FUN_6796bc`. `e9f663ff` = KDF del transport
`= hex(MD5(UUID_device || SALT@0x76cc10))` (SALT = `9B4F4CE2168E11EF8DCE000C297524BB`). Si hiciera falta
derivarlas: capturar el literal fuente (hook a `FUN_683660` MD5-hex o al hex-decode `0x6796bc`).

---

## 6★. BITÁCORA DE CRACKEO — cómo se descubrió y VERIFICÓ cada valor (proceso real)

> Esta sección cuenta, por valor, **cómo se crackeó realmente** (con dead-ends y razonamiento) y
> **cómo se comprobó que era correcto**. Sirve para entender el "por qué" y para re-crackear.

### A) Que el vivo va por el CDN `cfl` + el path `/live/<channel>.m3u8`
- **Dead-end inicial:** se asumió que el vivo necesitaba el redirect `/slb` a `nvuos` (P2SP) porque el
  app lo hace. Se crackeó todo el cripto de ese camino (Función A, §6.2) y aun así el `GET /slb` daba
  **401/503** desde la Mac (muro de red, §6.1). Meses trabados ahí.
- **La pista correcta:** "probar lo que hicimos con las películas". `download_iptv.py` (VOD) bajaba
  archivos del CDN `sign_type=cfl` (Cloudflare) **directo**, con `Content-Auth` en header, sin `/slb`.
- **Proceso:** (1) `get_slb(live)` mostró que además de la entrada `cs` (nvuos) hay entradas
  **`tag=live, sign_type=cfl`** (niguof/aluve). (2) Al pegarle a esos hosts con el `url` como
  Content-Auth → pasó de 503/401 a **HTTP 404** (¡request aceptado, sólo faltaba el path!). (3) El
  path exacto se sacó con **tcpdump** del tráfico real del app reproduciendo un canal (§7.3): el pcap
  reveló en claro `GET /live/<channel>.m3u8` y los segmentos `/live/<channel>/<channel>_shisui_<ts>.ts`
  a hosts CDN variables. (Nota: el media del player NO pasa por el hook de libranger; por eso tcpdump.)
- **Verificación:** `GET http://niguof.vynbszicd.com/live/<channel>.m3u8` → **200** con m3u8 válido;
  y un segmento firmado con sign_o3 → **200, 3.3 MB, primer byte 0x47** (sync MPEG-TS). Repetido:
  **6/6 segmentos** de un m3u8 fresco dieron TS válido.

### B) `sign_o3` (SALT + `tweaked_md5` + fn de compresión `0x529178`)
- **Ablación de red (tcpdump):** re-enviando requests reales con ediciones → `sign2` alterado = 401;
  `start_moment` viejo = 401. Conclusión: no hay atajo por replay, hay que generar el `sign2` fresco.
- **Estructura del mensaje (Frida):** hook a `libc write()` y a `MD5_Update (0x529044)` **uniendo los
  chunks** → el mensaje EXACTO de 118 bytes: `token=<..>&sign2_method=sign_o3&instance=0&start_moment=<m>`
  + `salt3333=4` + 11 bytes binarios. El SALT es **constante global** (igual en toda sesión/token).
- **El código (radare2):** `0x529178` usa IV/K/shifts/F estándar de MD5, PERO
  `md5_estándar(mensaje) ≠ sign2` → la compresión está **modificada en el *message schedule*** (qué
  palabra usa cada ronda; ronda 0 usa M[10]; grupo-1 = [10,11,12,13,14,15,6,7,8,9,0,1,2,3,4,5]; hay 4
  rondas anómalas). Reimplementar a mano era frágil.
- **La solución (Unicorn):** **emular la fn de compresión real `0x529178`** (mapear ELF + relocs
  R_AARCH64_RELATIVE/DT_RELR, escribir state16+block64, `emu_start`). `sign_o3.py`.
- **Verificación:** hook al `write()` del app, capturar `(token, start_moment, sign2)` reales →
  `sign_o3(token, start_moment)` coincidió **5/5 en vivo**. Detalle: `SIGN_O3_CRACK.md`.

### C) Función A — key `d5b1d91c`, iv `19aecdc8`, alfabeto REQUEST (el crack más difícil)
- **Dead-ends (semanas):** el `auth=` decodificado (con el alfabeto estándar) daba 480B de entropía
  ~7.6. Se probó: descifrar con ~15 claves capturadas (hexdecode/wrappers/transports) = basura;
  hookear TODAS las AES-block (`0x5c1644`/`0x5c65d0`, leyendo master key en roundkeys[0:16] con
  word-swap) = ninguna descifra; hookear todos los `0x678b14` = ninguno produce el `auth=` enviado;
  scan del binario por la clave = nada. El patrón de divergencia byte-31 entre 2 capturas hizo creer
  que era **CFB** y que había un **"cipher inlined / KEY_X"** — **TODO era una pista falsa.**
- **El giro (Ghidra):** decompilar en headless (`ghidra_scripts/SvsDump/SvsFind.java`) reveló que
  **`FUN_003ff160` (`0x2ff160`) es el ÚNICO caller del encoder base64 `FUN_004086ac` (`0x3086ac`)** →
  TODOS los `auth=` salen de ahí: `ret = base64( &DAT_0086cab0, encrypt_0x678b14(pt, key=[param_2+8]) )`.
- **Capturar la clave real (Frida):** hook a `0x2ff160` leyendo el retorno `std::string` (en **x8**,
  ABI de RVO), el transport en x0, plaintext en x1, y **key = std::string en [x0+8]**. Resultado: el
  retorno == el `auth=` ENVIADO, con **key = `d5b1d91c`** y plaintext `media_encrypted=0&sign_type=cs…`.
  (`frida/svs_ff160b.py`.)
- **El verdadero muro — el ALFABETO:** con esa key y CBC, el bloque descifrado seguía dando basura.
  El decompilado mostró que el encoder usa el alfabeto `&DAT_0086cab0`, **deobfuscado por una rutina
  XOR al inicio de la fn** (en el binario estático es `.bss`=0xff). Se leyó en **runtime**
  (`base + 0x76cab0`, 64 bytes) → **es un alfabeto DISTINTO** al de la respuesta:
  `jWB7YtC3n9iXbEkUcJl1VxF4STpQoOIaRmh2M-efAgLwPqGr6uyD5vNsdH_Kz0Z8` (marcador `"req:"` 12B antes).
  **Ése era el "muro" de meses:** se decodificaba con el estándar → basura → falsas teorías.
- **Verificación:** decodificar el `auth=` enviado con el alfabeto REQUEST + AES-CBC(d5b1d91c, iv
  recuperado `19aecdc8`) → querystring 100% legible; y encrypt(querystring) → `auth=` **idéntico**.
  **2/2 round-trips exactos** sobre `auth=` reales de sesiones distintas → key/iv/alfabeto FIJOS. El
  iv se recuperó asumiendo el P0 conocido (`media_encrypted=`) y confirmando en bloques ≥1.

### D) Función B — keys de la respuesta SVS
- **Método:** hook al wrapper de decrypt (`0x678cf0`) y al loop CBC-dec (`0x5cc6a4`), volcando
  `key/iv/ciphertext/plaintext` de TODAS las operaciones AES-CBC durante el resolve
  (`frida/svs_crypto.py`, `frida/svs_bt_decrypt.py`). La op que descifra la respuesta de servers
  (~512B) da `key=d5b1d91c, iv=e130e232`; la de la respuesta "auth" da `e9ef5394/71e9775c`.
- **Formato:** la respuesta es `base64_ESTÁNDAR → [4-byte header BE = len][AES-CBC ct] → PKCS7`
  (saltar 4 bytes antes del AES).
- **Verificación:** descifra los blobs capturados exactamente → `{"servers":[{"media_url":
  "http://149.34.241.153:8119/live/?...&token=<lc>&trans_id=..."}]}` legible. `149.34.241.153:8119`
  es estático.

### E) Los offsets de funciones (cómo se ubicaron)
- Por **strings + xrefs en Ghidra**: `"auth="` (@0x76d140), `"/slb/v9/live"` (@0x76cf28/0x76d594),
  `"req:"` (@0x76caa4), el alfabeto base64, y la tabla de senos de MD5 (`0xd76aa478…` → localiza los
  MD5/sign_o3). El offset del alfabeto REQUEST se derivó del decompilado de `FUN_003ff160`
  (`FUN_004086ac(&DAT_0086cab0, …)` → `0x86cab0` Ghidra − `0x100000` = `0x76cab0` runtime).
- Mapeo de direcciones confirmado con una fn conocida: `0x529178` en r2/Frida (base+off) = el prólogo
  de la compresión de sign_o3. Ghidra = vaddr original + `0x100000`.

---

## 7. Métodos de re-extracción (la caja de herramientas)

### 7.1 Frida — hook por offset (base + vaddr original)
- Direcciones = **vaddr original** del `.so`. En Frida: `module.base.add(0xVADDR)`. (En Ghidra sumar
  `0x100000`; en r2 = vaddr original tal cual — verificar con `0x529178` = prólogo de sign_o3.)
- **Attach por device correcto:** `dev = frida.get_device('emulator-5554')` (NO `get_usb_device`).
- **Ganar la carrera del arranque** (el cripto corre muy temprano): instalar hooks al cargar libranger
  hookeando `android_dlopen_ext` (frida 17: `Module.getGlobalExportByName("android_dlopen_ext")`, NO
  `Module.findExportByName`). Patrón en cualquier `frida/svs_*.py` reciente.
- **Disparo fiable de un resolve fresco:** el resultado se cachea SÓLO en memoria (no en disco) →
  `adb -s emulator-5554 shell am force-stop com.xuper.netxxus` + `dev.spawn([PKG])` re-resuelve. (NO
  usar `pm clear`.) Cambiar de canal por attach usa cache (no re-dispara).
- **Capturar requests en claro:** hook al `memcpy` dentro de `mbedtls_ssl_write` en `0x71b4c0`
  (x1=src, x2=len; filtrar primer byte `G/P/H`). Sólo ve el tráfico de libranger (/slb, DoH,
  telemetría) — **NO el media del player** (eso va por otro stack → usar tcpdump, §7.3).

### 7.2 Offsets clave (vaddr original de `libranger-jni.so`, verificados 2026-08-09)
```
0x529178  compresión MD5-tweak de sign_o3 (emulada con Unicorn)
0x529044  MD5_Update impl-B (para reconstruir el mensaje + SALT de sign_o3)
0x71b4c0  memcpy dentro de mbedtls_ssl_write (capturar requests en claro)
0x678b14  wrapper AES-CBC ENCRYPT: enc(keyHex, ivHex, pt, len, out, outlen)  [PKCS7]
0x678cf0  wrapper AES-CBC DECRYPT: dec(keyHex, ivHex, in, len, out, outlen)  [strip PKCS7]
0x6796bc  hex-decode (hexstr 32 chars → 16 bytes)   ;  0x683660 MD5-hex
0x5c1644  AES-encrypt-block (usa Te0)  ; 0x5c65d0 bloque AES ; 0x5cc3e8/0x5cc6a4 CBC enc/dec loop
0x2ff160  FUN_003ff160 = ÚNICO método encrypt→auth= (base64(alfabeto@0x76cab0, enc_0x678b14(pt, key=[obj+8])))
0x3086ac  FUN_004086ac = encoder base64 (toma el alfabeto como arg0)
0x76cab0  ALFABETO base64 del REQUEST (deobf en runtime)   ; 0x76caa4 marcador "req:"
0x76cc10  SALT del KDF del transport (9B4F4CE2168E11EF8DCE000C297524BB)
0x76cf28 / 0x76d594  "/slb/v9/live"   ; 0x76d140  "auth="
```
Si el binario cambia y los offsets se mueven: re-ubicarlos por **strings/xrefs** en Ghidra (buscar
`"auth="`, `"/slb/v9/live"`, el alfabeto base64, `"req:"`, la tabla de senos MD5 `0xd76aa478`).

### 7.3 tcpdump — descubrir las URLs de media reales (cómo se halló el path `/live/…`)
```bash
DEV=emulator-5554
adb -s $DEV shell "su 0 sh -c 'nohup tcpdump -i any -s0 -w /data/local/tmp/live.pcap &'"
adb -s $DEV shell monkey -p com.xuper.netxxus -c android.intent.category.LAUNCHER 1
# reproducir un canal (taps), esperar ~20s
adb -s $DEV shell "su 0 sh -c 'pkill -2 tcpdump'"
adb -s $DEV pull /data/local/tmp/live.pcap .
strings live.pcap | grep -aE "^GET .*(\.m3u8|\.ts)"     # ← revela /live/<channel>.m3u8 y los .ts
strings live.pcap | grep -aE "^Host: "                  # ← revela los CDN hosts (niguof/tdgao/...)
```
El endpoint P2SP `149.34.241.153:8119` es HTTP plano (se ve completo en el pcap); los cfl van por
puerto 80 HTTP (también legibles). Los headers completos del request salen con
`strings -n6 live.pcap | grep -aA14 "GET /live/<channel>.m3u8 HTTP"`.

### 7.4 Leer `std::string` de libc++ en Frida (para keys/iv que son std::string)
```
byte0 = *(ptr)
if (byte0 & 1) == 0:   # SSO (short): size = byte0>>1, data = ptr+1
else:                  # long:        size = *(ptr+8), data ptr = *(ptr+16)
```
El valor de retorno de funciones que devuelven `std::string` (RVO) va en **x8** (no x0); los args se
corren (x0, x1, …).

### 7.5 Ghidra headless (para RE del cripto)
```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
GH=/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless
PROJ=<scratchpad>/ghproj         # proyecto ya analizado: magia / libranger-deobf.so
"$GH" "$PROJ" magia -process libranger-deobf.so -noanalysis -scriptPath <ABS_DIR> -postScript X.java
```
- **Ghidra addr = vaddr original + 0x100000** (imagebase 0x100000). r2 usa el vaddr original tal cual.
- Scripts útiles ya escritos: `ghidra_scripts/SvsDump.java` (decompila una lista de fns + xrefs al
  alfabeto), `SvsFind.java` (halla los callers del encoder base64). La clase pública debe llamarse
  igual que el archivo; `-scriptPath` absoluto. Un headless a la vez (lock por proyecto).
- Binario deobfuscado: `libranger-deobf.so` (runtime .data overlaid; gitignoreado). El original:
  `lib/arm64-v8a/libranger-jni.so` (extraer del APK).

---

## 8. Gotchas (lo que hace perder tiempo)

- **Alfabeto base64 distinto request vs respuesta** — el error central que costó meses. El request
  (`auth=`) usa `jWB7Yt…`; la respuesta usa el estándar `B8oOvN…`. Decodificar con el equivocado da
  basura y falsas conclusiones ("cipher inlined / KEY_X / CFB"). No las hay: es AES-CBC plano.
- **El orden de campos del querystring VARÍA** por request → no asumir un plaintext fijo al testear.
- **`frida.get_usb_device()` agarra el teléfono real** ("SM S926B") → usar `get_device('emulator-5554')`.
- **El media del player NO pasa por libranger** → no se ve con el hook de ssl_write; usar tcpdump.
- **Segmentos en vivo expiran en segundos** → m3u8 fresco + segmento inmediato; `sign2` nuevo por request.
- **nvuos/`/slb` da 401/503 desde la Mac** (Cloudflare/binding server-side) → no es el camino; usar cfl.
- **`cdn_type` sobra** en el querystring del `/slb` (si se usa la ruta P2SP): con él → 503, sin él → 401.
- **No `pm clear`** (rompe la activación un rato). Para resolve fresco: `am force-stop` + spawn.
- **DIAGNÓSTICOS FALSOS del cripto SVS que costaron semanas** (no volver a caer):
  - *"El AES usa instrucciones ARM crypto (AESE/AESD), no hay S-box en el binario"* → **FALSO.** Es
    **AES-128-CBC por software estilo mbedTLS** (0 instrucciones aese/aesd en `.text`); las tablas Te0/
    inv-sbox SÍ están, pero **XOR-ofuscadas** y deobfuscadas en runtime (por eso "no aparecían").
  - *"Modo CFB"* (por 2 `auth=` que divergían en el byte 31) y *"cipher inlined / KEY_X / la clave no
    existe"* → **FALSO.** Es CBC plano con **key/iv FIJOS**; la divergencia era por el **orden variable
    de campos** del querystring (P0 distinto), no por el modo.
  - *"la clave `d5b1d91c` es un decoy que no se envía"* → **FALSO.** ES la clave real; lo que engañaba
    era decodear con el **alfabeto base64 estándar** en vez del **alfabeto REQUEST** (`jWB7Yt…`).
  - **No confundir el AES del SVS con el AES del media P2SP**: los bloques `0x5c65d0`/`0x5c1644` (y el
    core `0x5cc100`) los comparte el **descifrado de media P2SP**, que dispara MUCHÍSIMO durante el
    streaming y ahoga al del SVS (1 sola llamada). Hookear "todas las AES-block" captura P2SP, no el
    SVS → por eso ninguna clave matcheaba. El encrypt→`auth=` real es **sólo** `0x2ff160` (§7.2).
- **Docs `SVS_HANDOFF.md` y `SVS_CAMINOS.md` están SUPERSEDIDOS** (§10): reflejan el estado ANTES de
  crackear Función A y de hallar el camino cfl, y contienen esos diagnósticos falsos. Leer sólo este
  runbook + `SVS_FUNCION_A_HANDOFF.md`.
- **El estado COMMITEADO del repo es viejo**: los últimos commits (`bee8db6`, `24f0e86`…) son los docs
  antiguos; todo lo que funciona (`MAGIA_RUNBOOK.md`, `svs_cipher.py` Función A/B, `live_cfl.py`) está
  **sin commitear** en el working tree. Un `git log` engaña — mirar los archivos, no el historial.
- **Commits sólo como `lordmacu`**, sin coautoría (ver CLAUDE.md).

---

## 9. Verificación rápida end-to-end (sanity check)
```bash
cd /Users/cristian/magia
python3 svs_cipher.py            # self-test Función A+B (round-trips)  -> "self-test OK"
python3 - <<'PY'                 # vivo por cfl (m3u8 + 1 segmento)
import os; from dotenv import load_dotenv; load_dotenv()
from iptv_client import IPTVClient; import live_cfl, requests
c=IPTVClient(); ch="cyx_50fdcc0817d61_720p"     # o uno fresco de live_data(76182)
host,url,lic,tok=live_cfl.resolve_live_cfl(c,ch)
H=lambda: {"Content-Auth":live_cfl._seg_auth(url,tok),"Content-License":lic,
           "User-Agent":"Ranger/4.9.4-17294ac0","App":live_cfl.APP,"App-Version":live_cfl.AVER}
m=requests.get(f"http://{host}/live/{ch}.m3u8",headers=H()).text
seg=[l for l in m.splitlines() if l.startswith("http") and ".ts" in l][0]
r=requests.get(seg,headers=H()); print("seg", r.status_code, len(r.content), "TS" if r.content[:1]==b'\x47' else "??")
PY
```
Esperado: `seg 200 <~3MB> TS`. Si falla: revisar `sign_o3` (§5), headers/host (§7.3), o re-leer get_slb.

---

## 11. Cuentas / Auth (login, registro, recuperar contraseña)

Todo por la **API del portal** (`iptv_client.py`), 100% Python, sin adb.

### Hash del password (¡el que costó!)
El server espera **`MD5(password + "cloudstream")`** hex-minúsculas (salt fijo `"cloudstream"`,
decompilado: `u9/AbstractC5729e.m22190c` = `MD5((str+"cloudstream").getBytes())`, UTF-8).
**NO es MD5 plano** — el código viejo usaba plano y por eso el login fallaba con credenciales
correctas. Helper: `IPTVClient._hash_pwd(password)`.

### Endpoints y `type`
| Método (`iptv_client.py`) | Endpoint | Body |
|---|---|---|
| `activate()` | `v8/active` | free por device SN → userId/userToken |
| `login(email, pwd)` | `v8/login` | accountType="2", userName, password=hash, type="1" |
| `send_email_verify_code(email, type_)` | `v2/sendEmailVerifyCode` | {email, type, userId, userToken} |
| `validate_verify_code(email, code, type_)` | `v2/validateVerifyCode` | **`VerifyEmailCodeBean`** = {type, email, verifyCode, userToken, userId} |
| `bind_email(email, pwd, type_)` | `v2/bindEmail` | {email, pwd=hash, type, userId, userToken} |
| `reset_pwd(email, newpwd, code, type_)` | `v4/resetPwd` | {type, email, password=hash, verifyCode, ...} |

**`type` (mapeado desde las pantallas del app):**
- `"1"` = **registro / bind email** (`na/C4596a`: setea `bindMail=1`, `hasPwd=1`).
- `"2"` = cambiar (email/pwd) (`na/C4598c`).
- `"3"` = **reset / recuperar contraseña** (`s8/m1`, `EmailResetPwdBean("3",…)`).

### Flujos (verificados en vivo 2026-08)
- **Login:** `login(email, pwd)` → userToken (cuenta premium). ✅
- **Recuperar contraseña:** `send_email_verify_code(email, "3")` → (código al email) →
  `reset_pwd(email, newpwd, code, "3")` → `login`. ✅ (probado end-to-end).
- **Registro (bind email):** `send_email_verify_code(email, "1")` → `validate_verify_code(email, code, "1")`
  → `bind_email(email, pwd, "1")` → `login`. ✅ (probado end-to-end 2026-08-10 con
  lacasitadelsabor05@gmail.com → validate `成功`, bind `成功`, login OK userId 948922830).
  **CLAVE:** el `validate` es **obligatorio** antes del bind — si se omite o falla, el bind devuelve
  `portal100073 验证码不匹配` ("código no coincide"). El bean del validate NO es `CheckVerifiCodeBean`
  (phone/verificationCode/password — daba `请求参数异常`) sino **`VerifyEmailCodeBean`**
  {type, email, verifyCode, userToken, userId}. Ruta decompilada: pantalla registro `na/C4596a`
  → `m713b` → `C1035f.D0` → `z1.q3` → `VerifyEmailCodeBean` → `r0` = `v2/validateVerifyCode`;
  el bind es `m590b` → `C1035f.m5099h` → `J0` = `v2/bindEmail`.

### Reglas de negocio / trucos
- **1 email por device/appCode:** un dispositivo (SN) sólo puede bindear UN email. Intentar un
  segundo → `aaa100077` "邮箱账户不可重复". Para registrar otro email de verdad hace falta un **SN nuevo**.
- **Truco Gmail `+`:** `cuenta+algo@gmail.com` el server lo ve como email NUEVO y el código llega al
  inbox `cuenta@gmail.com`. Útil para probar registro con una sola casilla (verificado: send-code OK).
- Errores del server (Chino): `aaa100003`=usuario no existe, `aaa100022`=user/pass inválido,
  `aaa100077`=email ya bindeado en el appCode.

### CLI (`magia.py`)
Menú **Auth** (al arrancar): **Free tier / Iniciar sesión / Registrarse / Recuperar contraseña**.
Password oculto (`ask_secret`), guardado opcional en `.env` (`IPTV_USERNAME`/`IPTV_PASSWORD`, plano;
se hashea al usar). Funciones: `register_account()`, `recover_password()`, `_maybe_save_creds()`.

---

## 10. Índice de documentos y scripts
- **Este runbook** — el camino correcto + re-extracción. **Es la fuente de verdad; empezar acá.**
- `SIGN_O3_CRACK.md` — cómo se crackeó `sign_o3` (Unicorn + MD5-tweak). Vigente.
- `SVS_FUNCION_A_HANDOFF.md` — historia del cripto SVS (Función A), con el detalle del RE. Vigente.
- ⚠️ **SUPERSEDIDOS (no confiar — tienen conclusiones ya DESMENTIDAS):**
  - `SVS_HANDOFF.md`, `SVS_CAMINOS.md` — de cuando Función A se creía bloqueada y NO se conocía el
    camino cfl. Afirman "AES con instrucciones ARM crypto" y "clave no encontrada / emular con
    so_emulator" → **ambas cosas resultaron FALSAS** (es AES-CBC software con key fija; ver §6/§8).
    Se conservan sólo como historial del proceso. **La verdad está en este runbook.**
  - `svs_bootstrap.py` — solución app-assisted (spawnea la app ~15s por sesión). **RECHAZADA por el
    usuario** (el objetivo es 100% Python sin app en runtime). No usar ni proponer.
- Memoria del agente (2 stores): `~/.claude/projects/-Users-cristian-magia/memory/` (`magia-live-runbook.md`
  ⭐, `magia-svs-crypto.md`, `magia-no-bootstrap.md`) y `~/.claude/projects/-Users-cristian-crunch/memory/magia-sign-o3-investigation.md`
  (bitácora larga del RE del SVS: sesiones, dead-ends, addresses).
- Código: `live_cfl.py` (vivo, camino correcto), `download_iptv.py` (VOD), `sign_o3.py`, `so_emulator.py`,
  `svs_cipher.py` (Función A/B), `svs_client.py` (P2SP, muro de red), `aes_mbed.py`, `iptv_client.py`.
  Frida: `frida/svs_*.py` (93 scripts; los útiles citados en §6/§7). Ghidra: `ghidra_scripts/{SvsDump,SvsFind}.java`.
