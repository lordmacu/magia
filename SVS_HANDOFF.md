# Handoff — cerrar el TV en vivo 100% independiente (crackear el redirect SVS)

> Documento de traspaso. Todo lo necesario para continuar sin contexto previo. Leer también
> [SIGN_O3_CRACK.md](SIGN_O3_CRACK.md) (cómo se crackeó la firma) y [SVS_CAMINOS.md](SVS_CAMINOS.md)
> (los caminos). Estado: `sign_o3` **resuelto**; el **transporte del SVS ya está crackeado**
> (API encontrada y replicable); falta solo la **capa AES de 2 blobs**.

## 0. Objetivo

Reproducir el header `Content-Auth` del CDN para abrir TV en vivo en VLC/mpv desde el CLI,
**sin app ni emulador**. Ya está el 90%: falta obtener el prefijo del Content-Auth del iCDN
(`host + token lowercase + trans_id`) que hoy produce el **redirect SVS** de la app.

## 1. Lo que YA funciona (en `main`)

- **`sign_o3.py`** — genera el `sign2` en Python puro emulando con Unicorn la compresión
  MD5-tweak de `libranger-jni.so` (fcn `0x529178`). **Verificado 5/5 contra la app en vivo.**
  `python3 sign_o3.py` corre los vectores.
- **`live_stream.py`** — `LiveSession` + `LiveProxy`: proxy local que re-firma cada segmento
  con `sign_o3`. **Ya transmite en vivo (200 OK) si se le da el prefijo del Content-Auth.**
- **`so_emulator.py`** — toolkit para emular funciones nativas ARM64 (mapea ELF + relocaciones;
  helpers `trace_calls`/`watch_reads`/`capture_at`). **Es la herramienta para lo que falta.**
- **`magia.py`** — `stream_live` independiente + `get_live_cdn_auth`. Hoy falla con mensaje
  claro porque `get_slb` no trae el prefijo sign_o3 (lo produce el SVS).

## 2. EL GAP exacto

`get_slb(type=merge, live_codes=[canal])` devuelve CDN **CF** (`sign_type=cfl`) e **iCDN**
(`sign_type=cs`, host `nvuos…` tras Cloudflare). Ninguno trae el prefijo con `sign2_method=sign_o3`.
La app hace un **redirect SVS** contra el host iCDN que devuelve el endpoint real
`149.34.241.153:8119` + **token lowercase** + `trans_id`. `sign_o3` firma ESE request final.

## 3. BREAKTHROUGH — el SVS ya está capturado y es replicable

**Hook que funciona (clave):** en **spawn fresco** (antes de que el P2SP inunde las funciones
TLS), hookear el `memcpy` DENTRO de `mbedtls_ssl_write` en **`libranger!0x71b4c0`**
(`x1`=src=plaintext TLS, `x2`=len). Filtrar por primeros bytes `GET/POST/HTTP`. Script listo:
[`frida/svs_capture_request.py`](frida/svs_capture_request.py). Captura:

```
GET /slb/v9/live?auth=<blob ~658 chars base64-custom> HTTP/1.1
Host: nvuos.7r03dh6rph.com          (= main_addr del CDN icdn en get_slb)
App: com.android.msandroid
App-Version: 49902
Content-Type: application/octet-stream
Ranger-Id: <35 chars>
User-Agent: Ranger/4.9.4-17294ac0
```
(Antes el app resuelve todo por DoH: `POST https://dns.google/dns-query`.)

**Replay desde Python → 200 OK.** Script: [`frida/svs_replay.py`](frida/svs_replay.py). La
respuesta es otro blob base64-custom.

**base64-custom de Ranger:** `B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7`
(traducir custom→estándar, luego `base64decode`).

- Decodificados: **request → 480 bytes**, **response → 512 bytes**, ambos múltiplos de 16 y
  entropía ~7.5/8 → **AES cifrado** (NO plaintext).
- iCDN **`149.34.241.153:8119` es estático** (mismo IP en todas las sesiones capturadas).

## 4. Lo que FALTA (2 funciones de crypto) — plan concreto

Reversear el formato/clave a mano NO es viable (comprobado): el AES usa **instrucciones ARM
crypto** (AESE/AESD, sin S-box en el binario), y el plaintext del `auth=` es un **struct
binario** (todos los marcadores de texto —`link=icdn`, `session_id`, `main_addr=nvuos`— dieron
MISS en memoria durante el SVS). → Tratar el crypto como **caja negra y EMULAR** con `so_emulator`,
igual que se hizo con la compresión de `sign_o3`.

**Función A — construir+cifrar el `auth=`** (input: datos de get_slb; output: el blob):
1. En spawn fresco, hookear el rango de instrucciones ~antes de `0x71b4c0` (o usar Stalker sobre
   el hilo que llega al `GET /slb`) para ubicar la función que **produce el buffer del `auth=`**
   justo antes del ssl_write. Sus inputs son los datos de get_slb (session_id, token upper,
   group, user_id, dev_id) + Ranger-Id.
2. Emular esa función con `so_emulator.SoEmulator(...).call(addr, [args])`.

**Función B — descifrar el response** (input: blob de 512 bytes; output: iCDN host+token+trans_id):
1. Ubicarla capturando **DESPUÉS** de que llega el response (no al momento del request): hookear
   el lado `ssl_read` (buscar su `memcpy` análogo al de ssl_write) o poner MemoryAccessMonitor/
   búsqueda de `149.34.241.153` en memoria mientras la app **está streameando** (ahí sí aparece).
2. Emular esa función con `so_emulator`, o —más rápido para validar— usar la app como **oráculo
   Frida**: llamar la función de decode con un blob que fetcheás vos (`NativeFunction`) y leer el
   struct de salida.

**Con A+B:** Python arma el `auth=`, hace `GET /slb/v9/live?auth=…` al host icdn, decodifica el
response → `(149.34.241.153:8119, token lowercase, trans_id)`. Con eso `get_live_cdn_auth`
(en `magia.py`) devuelve el prefijo y el proxy `live_stream.py` + `sign_o3` transmiten solos.

## 5. Detalles de entorno (importante)

- App: `com.xuper.netxxus` ("Xuper Hydra"). APK: `/Users/cristian/mago/Xuper.Hydra.HDR.4KP.apk`.
  Lib nativa: `libranger-jni.so` (ARM64, OLLVM). Emulador: `emulator-5554` (adb).
- **Frida requiere Python 3.14**: `/opt/homebrew/opt/python@3.14/bin/python3.14` (el py3.9 del
  sistema tiene el binding roto). Para el cliente API + `so_emulator`: `/opt/homebrew/bin/python3`
  (tiene Crypto/requests/unicorn).
- Lanzar la app: `adb shell monkey -p com.xuper.netxxus -c android.intent.category.LAUNCHER 1`.
  Activity: `com.interactive.brasiliptv.ui.activity.WelcomeActivity`.
- **`libranger-jni.so` NO está en el repo** (propietario, gitignoreado). Extraerlo del APK a la
  raíz del repo: `lib/arm64-v8a/libranger-jni.so`. `sign_o3.py`/`so_emulator.py` lo cargan de ahí
  (o vía env `LIBRANGER_SO=/ruta`).
- `.env` con credenciales IPTV (local, gitignoreado). El cliente se auto-activa por device sn.
- Direcciones útiles en libranger: MD5-tweak compress `0x529178`; memcpy dentro de ssl_write
  `0x71b4c0`; cadena TLS `ssl_write_record 0x71fd3c`, `flush_output 0x694f18`, `bio_send 0x6984b0`.

## 6. Scripts de RE (en `frida/`)

- `svs_capture_request.py` — captura el request del SVS en claro (el hook clave).
- `svs_replay.py` — replica el request + decodifica los blobs base64-custom.
- (existentes) `frida_cdn_hook*.py`, `frida_vod_capture.py`, etc.

## 7. Memoria del agente

Hay una nota de memoria persistente muy detallada:
`~/.claude/projects/-Users-cristian-crunch/memory/magia-sign-o3-investigation.md`
(fórmula de sign_o3, todos los hallazgos del SVS, addresses, blockers y caminos).
