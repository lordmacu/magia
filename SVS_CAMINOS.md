# Redirect SVS — caminos para cerrar el TV en vivo 100% independiente

> Estado: `sign_o3` está crackeado y verificado (ver [SIGN_O3_CRACK.md](SIGN_O3_CRACK.md)), y el
> proxy re-firmante (`live_stream.py`) transmite en vivo **en cuanto tenga el prefijo del
> Content-Auth del iCDN**. Lo único que falta para independencia total es **replicar el redirect
> SVS/SLB** que le da a la app ese prefijo. Este documento reúne lo descubierto y los caminos.

## El gap

`get_slb(type=merge, live_codes=[canal])` devuelve `cdn_list` con tag=`live` de **dos** tipos, y
**ninguno** trae el prefijo con `sign2_method=sign_o3`:

| tipo | main_addr | sign_type | notas |
|---|---|---|---|
| CF | `http://<h>/v3/youshi/` | `cfl` | pre-firmado, pero da 403/404 desde el Mac; la app cae a iCDN |
| iCDN | hostname `nvuos…` (Cloudflare) | `cs` | **no** es el endpoint final; requiere el redirect SVS |

El endpoint real (`149.34.241.153:8119`) + el **token lowercase** + `trans_id` los produce el
**star proxy / P2SP** de libranger (`svs_address=xsvs.vfltbr.com:18084`, `tracker_list`,
`star_proxy=1`, `live_pcdn_mode=p2sp` en `play_params`). `sign_o3` firma el request **final** a
ese iCDN; el redirect SVS es el paso previo que aún no replicamos.

Datos clave (de sesión real con `.env`):
- token `get_slb` iCDN es **UPPERCASE** (ej. `89EA3014…`) y difiere del **lowercase** del
  Content-Auth (ej. `941d9896…`): el SVS lo transforma.
- `nvuos…` resuelve a IPs de **Cloudflare** (no al iCDN). `xsvs.vfltbr.com:18084` es **openresty**.
- El IP del iCDN **sí o sí viene de red** (no se puede derivar localmente).

## Lo que se investigó (y por qué se frenó)

- Tráfico SVS/API va por **TLS con mbedTLS estático** dentro de libranger (sin símbolos
  exportados de ssl/mbedtls; ofuscado OLLVM).
- Cadena de envío TLS ubicada por backtrace de records (`0x16/0x17 03`) desde `send()`:
  `send ← ranger!0x6984b0 (bio_send) ← 0x694f18 (flush_output) ← 0x71fd3c (ssl_write_record) ← [mbedtls_ssl_write] ← app`.
  **OJO:** esas son direcciones de RETORNO, no entries. Hookear `0x71b4f4` como entry fue un
  error (dispara en un hot-path con `x1`=struct `addbdec0…`, no plaintext). Hay que desasm
  hacia atrás hasta el prólogo para el entry real.
- El SVS es un evento **solo-de-arranque** (cambiar de canal NO lo re-dispara; el token de
  sesión es constante) y probablemente **protocolo binario** (el filtro GET/POST no capturó
  nada en spawn fresco). La capa P2SP llama a las funciones TLS a altísimo volumen → los hooks
  naive inundan/cuelgan.

## Caminos (elegir para la próxima sesión)

### 1. MITM + bypass de cert-pinning  ← recomendado
- La función de verificación x509 de mbedTLS se llama **1×/handshake** (no es hot → hookeable,
  a diferencia de `ssl_write`). Ubicarla en el rango `0x71xxxx`, hookearla para aceptar el CA de
  mitmproxy, enrutar el tráfico del emulador por el proxy y **leer el request/response del SVS
  en claro**. Con eso se replica el redirect en Python.

### 2. Hook quirúrgico de `mbedtls_ssl_write/read` en spawn fresco
- Encontrar el **entry real** (prólogo) de `mbedtls_ssl_write` (desasm desde `0x71b4f4`) y de
  `mbedtls_ssl_read`. Hookear solo en la ventana de arranque (antes de que el P2SP inunde) y
  volcar el plaintext del SVS (request + response), sea binario o no.

### 3. Test de derivación local del token (rápido, incierto)
- Probar si el **token lowercase + trans_id** se derivan localmente en libranger desde los
  datos de `get_slb` (token uppercase, `session_id`, `group`) — si así fuera, se emula esa
  función con [`so_emulator.py`](so_emulator.py). Aun así el **IP del iCDN** viene de red, así
  que el SVS no se evita del todo.

### 4. Emular el cliente SVS de libranger offline
- El más difícil: reconstruir la lógica del cliente star/P2SP dentro de libranger. Último recurso.

## PROGRESO — SVS capturado y replicable (transporte crackeado)

Hook clave que funciona: en **spawn fresco** (antes de que el P2SP inunde), hookear el
`memcpy` DENTRO de `mbedtls_ssl_write` en **`libranger!0x71b4c0`** (`x1`=src=plaintext,
`x2`=len) captura el plaintext TLS. Filtrando por primeros bytes `GET/POST/HTTP` se capturó
el **request completo del SVS**:

```
GET /slb/v9/live?auth=<blob ~658 chars base64-custom> HTTP/1.1
Host: nvuos.7r03dh6rph.com          (= el main_addr iCDN de get_slb)
App: com.android.msandroid
App-Version: 49902
Content-Type: application/octet-stream
Ranger-Id: <35 chars>
User-Agent: Ranger/4.9.4-17294ac0
```

(Antes el app resuelve los hosts por DoH: `POST https://dns.google/dns-query`.)

- **REPLAY desde Python FUNCIONA**: mismo GET a `https://nvuos.7r03dh6rph.com/slb/v9/live?auth=<blob>`
  con esos headers → **200**, body = otro blob base64-custom (684 chars).
- base64-custom alphabet: `B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7`
  (traducir custom→estándar, luego `base64decode`).
- Decodificados: **request → 480 bytes**, **response → 512 bytes**, ambos **múltiplos de 16 y
  alta entropía (~7.5/8) → AES cifrado** (no plaintext). El response descifrado (en el app) da
  el endpoint iCDN + token lowercase + trans_id (lo que va al Content-Auth).
- iCDN **`149.34.241.153:8119` es estático** (mismo IP en todas las sesiones).

### Lo que falta (crypto del blob) — via `so_emulator`
1. Emular/ubicar la función libranger que **construye+cifra el `auth=`** desde los datos de
   get_slb (session_id, token upper, group, user_id, dev_id, Ranger-Id).
2. Emular/ubicar la función que **descifra el response** (512 bytes AES → iCDN host + token
   lowercase + trans_id). Falta la **clave AES** (estática en libranger o de sesión).
3. Con (1)+(2): request al SVS desde Python → decode → prefijo Content-Auth → proxy + `sign_o3`
   = live 100% independiente.

Sugerencia para ubicar la clave AES: hookear las funciones AES de libranger (mbedtls_aes o
custom) durante el SVS en spawn fresco, o buscar en memoria el plaintext del `auth=` (contiene
`session_id`/`link=icdn`) justo antes del cifrado.

## Herramientas ya disponibles

- [`so_emulator.py`](so_emulator.py) — emula funciones nativas ARM64 (mapea ELF + relocaciones);
  helpers `trace_calls`, `watch_reads`, `capture_at` para descubrir.
- [`sign_o3.py`](sign_o3.py) — firma final lista (verificada 5/5 en vivo).
- [`live_stream.py`](live_stream.py) — proxy re-firmante; funciona con el prefijo del iCDN.

Cuando el camino elegido entregue `(host iCDN, token lowercase, trans_id)`, `get_live_cdn_auth`
en `magia.py` devuelve el prefijo y el proxy + `sign_o3` transmiten solos.
