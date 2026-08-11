# Cómo crackeamos `sign_o3` (sign2) de Magis TV — y qué logramos

> App: `com.xuper.netxxus` ("Xuper Hydra", variante Magis TV). Lib nativa: `libranger-jni.so`
> (Ranger CDN, ARM64, 7.9 MB, ofuscada con OLLVM). Objetivo: reproducir el header de
> autenticación del CDN **100% en Python**, sin depender de la app ni del emulador Android,
> para poder abrir la TV en vivo directo en VLC/mpv desde un CLI.

## TL;DR — lo que logramos

- **Fórmula completa del `sign2`** (reverse-engineered y verificada **5/5 contra la app EN VIVO**):

  ```
  SALT  = b"salt3333=4" + bytes.fromhex("980d0a1532c9c3821708c0")   # constante global
  msg   = f"token={TOKEN}&sign2_method=sign_o3&instance=0&start_moment={MOMENT}".encode() + SALT
  sign2 = tweaked_md5(msg)                                          # 32 hex lowercase
  ```
- `tweaked_md5` = un MD5 **modificado**. Primero se resolvió **emulando** la compresión real del
  `.so` con Unicorn; después esa emulación se usó como **oráculo** para derivar el algoritmo y
  reimplementarlo en Python puro. **Ya no hace falta el `.so` ni `unicorn`** (ver §"Cierre" abajo).
- Implementación lista para usar: [`sign_o3.py`](sign_o3.py). `python3 sign_o3.py` corre los
  vectores de verificación (5/5 OK).
- Además, con un `ncap` (captura de red) confirmamos **cómo hablar directo con el CDN** y qué
  valida (ver "Flujo de streaming" abajo).

## El reto

El CDN `149.34.241.153:8119` sirve la TV en vivo por **HTTP plano** (`GET /live/<canal>.m3u8`
y luego los `.ts`), pero **valida criptográficamente** un `sign2` que va en el header
`Content-Auth`, distinto en cada request (cambia con `start_moment`). Ese `sign2` lo genera la
lib nativa con un algoritmo propietario ("sign_o3"), ofuscado. Sin reproducirlo, no hay
streaming independiente.

## Metodología (paso a paso, lo que funcionó)

### 1. Captura de red (`ncap`) — entender el protocolo
`tcpdump` en el emulador (`adb shell tcpdump -w cap.pcap`) mientras la app reproducía. Con eso:
- Vimos la secuencia real: `GET /live/<canal>.m3u8` → luego los segmentos `.ts`, **todos con
  headers `Content-Auth` + `Content-License`** y respuesta `200/206`.
- **Ablación** (re-enviando peticiones reales desde el Mac con ediciones quirúrgicas): con
  `sign2` alterado → **401**; con `start_moment` viejo → **401**; sin `Content-License` → 401;
  faltando `Ranger-Id`/`X-Buffer` → 409. Conclusión: **no hay atajo por replay**, hay que
  generar un `sign2` fresco y válido por request. (Dato: la IP pública del Mac coincidía con el
  `client_ip` del header, así que el CDN no ata por IP de forma que estorbe.)

### 2. Frida — encontrar la estructura del mensaje
Hooks dinámicos sobre el proceso (`frida -U -p <pid>`):
- Hook a `libc write()` → capturamos los headers `Content-Auth` completos y confirmamos qué
  campos varían (`start_moment`, `sign2`) y cuáles no (token, expired, dev_id, …).
- Localizamos el MD5 en la lib buscando la tabla de senos de MD5 (`0xd76aa478…`) y las
  constantes inmediatas. Hay **dos** implementaciones de MD5; la del `sign2` es la que llamamos
  "impl-B" (`update=0x529044`, `compresión=0x529178`, `final=0x529bcc`).
- Hookeando `MD5_Update (0x529044)` y **uniendo sus chunks** reconstruimos el **mensaje exacto
  de 118 bytes** que se hashea: `token=<token>&sign2_method=sign_o3&instance=0&start_moment=<m>` +
  `salt3333=4` + 11 bytes binarios. Ese "salt" es **constante global** (igual en todas las
  sesiones/tokens).

### 3. radare2 — leer el código del firmado
Con el binario estático (`r2 -e scr.color=0 -c 's 0x...; af; pdf'`):
- `fcn.5833a0` resultó ser un helper `md5_hex(str)` (init→update→final→codificar hex).
- Encontramos que `sign2` lo produce **impl-B** y que su compresión `0x529178` usa: **IV estándar**
  (`67452301…`), **constantes K estándar en orden**, **shifts estándar en orden**, **F estándar**
  `(b&c)|(~b&d)`, y **carga de palabras little-endian estándar** (`0x529d00`).
- Contradicción clave: con TODO estándar, `md5_estándar(mensaje) ≠ sign2`. O sea, la compresión
  está **modificada** en algo sutil: el *message schedule* (qué palabra de las 16 usa cada ronda).
  La ronda 0 usa `M[10]` en vez de `M[0]`; el grupo-1 = `[10,11,12,13,14,15,6,7,8,9,0,1,2,3,4,5]`.
  (Además hay 4 rondas "anómalas" que no encajan con ninguna de las 4 F-functions estándar.)

### 4. Unicorn Engine — replicar la compresión exacta (la pieza clave)
En vez de pelear con las rondas ofuscadas a mano, **emulamos directamente la función de
compresión real del binario** con [Unicorn](https://www.unicorn-engine.org/) (CPU emulator).

**Cómo lo usamos** (ver `TweakedMD5` en [`sign_o3.py`](sign_o3.py)):
1. **Mapear el ELF**: parseamos los *program headers*, mapeamos todos los segmentos `PT_LOAD`
   en sus `p_vaddr` con su contenido de archivo (`mu.mem_map` + `mu.mem_write`).
2. **Aplicar relocaciones** `R_AARCH64_RELATIVE` (y `DT_RELR`): **esto es imprescindible** —
   el ofuscador OLLVM usa *saltos calculados* (`br x9`) que leen direcciones de código desde
   tablas en `.data`; en el archivo esas tablas están sin resolver (con addend), y el linker las
   parchea al cargar. Si no aplicas las relocaciones, el primer salto va a `0x0` y explota.
   Parseamos `DT_RELA/RELASZ/RELAENT` (tipo `1027`) y `DT_RELR`, y como la base = 0, escribimos
   `*(offset) = addend`.
3. **Preparar la llamada**: reservamos stack y un scratch; escribimos el `state` (16 bytes) y el
   `block` (64 bytes) en memoria; ponemos `x0=state_ptr`, `x1=block_ptr`, `LR=RET_MAGIC`.
4. **Ejecutar** `mu.emu_start(0x529178, RET_MAGIC)` y leer de vuelta el `state` (16 bytes) = el
   nuevo estado MD5 tras comprimir ese bloque.
5. Alrededor de esa compresión emulada montamos el MD5 completo en Python (IV estándar + bucle
   de bloques + padding estándar con el bit-length). Reutilizamos **una sola** instancia de
   Unicorn para que cada `sign2` sea rápido.

Con esto, `tweaked_md5(mensaje) == sign2` **exacto**.

### 5. (Bonus) extraer el schedule con el emulador como oráculo
Ya con la compresión emulada funcionando, instrumentamos las instrucciones `ror` (una por ronda)
para leer el valor rotado y **derivar el schedule**: grupo-1 = `[10,11,12,13,14,15,6,7,8,9,0,1,2,3,4,5]`,
grupos 2–4 = MD5 estándar, salvo **4 rondas (42,45,54,62)** cuyo cómputo no encaja con la forma
estándar. Por eso el camino robusto y verificado es el **emulador** (no una reimplementación a mano).

## Verificación

`sign_o3.py` trae vectores capturados del binario real y además lo cruzamos **en vivo**:
hookeamos el `write()` de la app, capturamos `(token, start_moment, sign2)` de peticiones nuevas,
y comparamos contra `sign_o3(token, start_moment)`:

```
5/5 coinciden con la app EN VIVO
```

## Flujo de streaming (lo que falta para el CLI completo)

Con `sign2` resuelto, el pipeline independiente es:
1. **API** (`play_live`/`get_slb` del portal — ya hay cliente en `iptv_client.py`): obtener
   `token` (Content-Auth) + `license` (Content-License, `scheme=md5-01`, dura ~6 días) + host CDN.
2. Construir el request: `GET http://149.34.241.153:8119/live/<canal>.m3u8` con headers
   `Content-Auth` (con `start_moment` fresco + `sign2` de `sign_o3()`), `Content-License`,
   `Ranger-Id`, `X-Buffer`, `App`, `App-Version`, `User-Agent: Ranger/4.9.4-...`.
3. Parsear el `.m3u8`, pedir los `.ts` (cada uno con su propio `Content-Auth` fresco) y pasarlos
   a VLC/mpv. (Verificado: headers correctos → 200; `sign2` basura → 401.)

Nota pendiente: falta confirmar la fórmula del token de `Content-License` (`scheme=md5-01`) —
probablemente el mismo `tweaked_md5` sobre campos `media_code/expired/token`.

## Herramientas usadas

- **tcpdump** (en el emulador vía adb) para el `ncap`.
- **Frida** para hooks dinámicos (encontrar el mensaje, el salt, las funciones MD5).
- **radare2** para el disassembly estático (identificar `0x529178` y confirmar IV/K/shifts/F).
- **Unicorn Engine** para emular la compresión real y replicar el MD5-tweak en Python puro.
- **Python 3** (`pip install unicorn`).

> Requisitos del módulo final: **ninguno**. Ni `unicorn`, ni el `.so`, ni Android/adb/Frida.

## Cierre (2026-08-11): fuera el `.so` — el MD5-tweak, resuelto

La emulación con Unicorn dejó de ser necesaria: sirvió de **oráculo** para derivar el algoritmo
y hoy `tweaked_md5.py` lo hace en Python puro.

**Cómo se derivó.** La función `0x529178` hace exactamente un `ror` por ronda (64 en total).
Hookeando cada uno con `UC_HOOK_CODE` y leyendo el registro fuente *antes* de ejecutar se obtiene

```
f_i = a + F(b,c,d) + K[i] + M[g]
```

Con el estado reconstruido ronda a ronda, se despeja `(F, g)` probando las 4 funciones estándar
por las 16 palabras y cruzando varias muestras aleatorias. Salieron **60 de 64 rondas** como MD5
estándar (con el schedule tweakeado en la 1ª vuelta). Las 4 restantes —42, 45, 54, 62— no daban
solución; se resolvieron exigiendo que `X − F(b,c,d) − M[g]` fuese **constante** entre muestras:
esa constante es `K'[i] − K[i]`.

**El tweak completo, entonces, es sólo:**

1. Schedule de la 1ª vuelta: `[10,11,12,13,14,15,6,7,8,9,0,1,2,3,4,5]` (vueltas 2–4 estándar).
2. Cuatro constantes K distintas — con pinta de erratas de transcripción (`db`→`bd`, `ad`→`da`):

   | ronda | K estándar | K real     |
   |-------|------------|------------|
   | 42    | `d4ef3085` | `d46f3085` |
   | 45    | `e6db99e5` | `e6bd99e5` |
   | 54    | `ffeff47d` | `ffecc47d` |
   | 62    | `2ad7d2bb` | `2da7d2bb` |

Todo lo demás —IV, F/G/H/I, shifts, padding little-endian, feed-forward Davies-Meyer— es MD5 de manual.

**Verificación** (`test_tweaked_md5.py`): `compress` idéntica al `.so` en 200 bloques aleatorios y
en casos borde; `digest_hex` idéntica en mensajes de 0–300 bytes incluidas las fronteras de padding
(55/56, 63/64); y los 5 vectores capturados de la app en vivo siguen dando 5/5. Probado además
**con el `.so` movido de sitio y `unicorn` bloqueado**: playlist en vivo `200` y segmento `.ts` real
descargado del CDN (primer byte `0x47`, sync de MPEG-TS).
