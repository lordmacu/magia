#!/usr/bin/env python3
"""tweaked_md5.py — El MD5 modificado de Magis TV, en Python puro.

Reemplaza la emulacion con Unicorn de `libranger-jni.so` (sign_o3.TweakedMD5): mismo
resultado bit a bit, sin binario propietario ni dependencias nativas.

QUE TIENE DE MODIFICADO (derivado con el emulador como oraculo, ver DERIVACION abajo):

  1. El *message schedule* de la 1a vuelta no es 0..15 sino
         [10,11,12,13,14,15,6,7,8,9,0,1,2,3,4,5]
     Las vueltas 2, 3 y 4 usan los indices estandar de MD5.
  2. Cuatro rondas -- 42, 45, 54 y 62 -- usan una constante K distinta. Su funcion F y
     su palabra del mensaje SI son las estandar; solo cambia la constante, y los cuatro
     valores parecen erratas de transcripcion del MD5 original (`db`->`bd`, `ad`->`da`).

Todo lo demas es MD5 de manual: mismo IV, mismas 4 funciones F/G/H/I, mismos shifts,
mismo padding little-endian y mismo feed-forward Davies-Meyer.

DERIVACION (reproducible): se hookean las 64 instrucciones `ror` de la funcion 0x529178
emulada, una por ronda, y se lee el valor pre-rotacion
    f_i = a + F(b,c,d) + K[i] + M[g]
De ahi se despeja (F, g) por ronda cruzando varias muestras aleatorias. Las 4 rondas sin
solucion se resuelven pidiendo que `X - F(b,c,d) - M[g]` sea CONSTANTE entre muestras:
esa constante es K'[i] - K[i].  Ver test_tweaked_md5.py, que compara contra el .so.
"""
import struct

__all__ = ["compress", "digest_hex", "K", "MD5_IV"]

_M32 = 0xffffffff

MD5_IV = bytes.fromhex("0123456789abcdeffedcba9876543210")

# K estandar de MD5: floor(abs(sin(i+1)) * 2**32)
K = [0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
     0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
     0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
     0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
     0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa,
     0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
     0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
     0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
     0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
     0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
     0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05,
     0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
     0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039,
     0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
     0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
     0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391]

# El tweak: 4 constantes cambiadas respecto al MD5 estandar.
K = list(K)
K[42] = 0xd46f3085      # estandar 0xd4ef3085
K[45] = 0xe6bd99e5      # estandar 0xe6db99e5
K[54] = 0xffecc47d      # estandar 0xffeff47d
K[62] = 0x2da7d2bb      # estandar 0x2ad7d2bb

_S = ([7, 12, 17, 22] * 4) + ([5, 9, 14, 20] * 4) + \
     ([4, 11, 16, 23] * 4) + ([6, 10, 15, 21] * 4)

# El tweak: schedule de la 1a vuelta (las otras tres son las estandar).
_ROUND1_SCHEDULE = [10, 11, 12, 13, 14, 15, 6, 7, 8, 9, 0, 1, 2, 3, 4, 5]

_G = _ROUND1_SCHEDULE + \
     [(5 * i + 1) % 16 for i in range(16, 32)] + \
     [(3 * i + 5) % 16 for i in range(32, 48)] + \
     [(7 * i) % 16 for i in range(48, 64)]


def compress(state16, block64):
    """Compresion de un bloque: replica fcn.529178 del .so. state/salida = 16 bytes."""
    a0, b0, c0, d0 = struct.unpack("<4I", state16)
    m = struct.unpack("<16I", block64)
    a, b, c, d = a0, b0, c0, d0

    for i in range(64):
        if i < 16:
            f = (b & c) | (~b & d)
        elif i < 32:
            f = (d & b) | (~d & c)
        elif i < 48:
            f = b ^ c ^ d
        else:
            f = c ^ (b | (~d & _M32))
        f = (f + a + K[i] + m[_G[i]]) & _M32
        s = _S[i]
        a, d, c = d, c, b
        b = (b + (((f << s) | (f >> (32 - s))) & _M32)) & _M32

    return struct.pack("<4I", (a + a0) & _M32, (b + b0) & _M32,
                       (c + c0) & _M32, (d + d0) & _M32)


def digest_hex(msg: bytes) -> str:
    """Digest completo. Padding little-endian estandar de MD5 (0x80, ceros, bitlen)."""
    state = MD5_IV
    for i in range(0, len(msg) - len(msg) % 64, 64):
        state = compress(state, msg[i:i + 64])
    rem = msg[len(msg) - len(msg) % 64:]
    final = rem + b"\x80" + b"\x00" * ((56 - (len(rem) + 1)) % 64) + \
        struct.pack("<Q", len(msg) * 8)
    for j in range(0, len(final), 64):
        state = compress(state, final[j:j + 64])
    return state.hex()


