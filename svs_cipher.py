#!/usr/bin/env python3
"""svs_cipher.py — Cripto del redirect SVS de Magis TV (Xuper Hydra) en PURO Python.
Reverseado de libranger-jni.so con Ghidra + Frida (emulador roteado).

============================ ESTADO ============================
✅ FUNCIÓN B (descifrar la respuesta SVS) — CRACKEADA y verificada en puro Python.
   Convierte el blob base64-custom de la respuesta -> JSON con el endpoint iCDN real
   (149.34.241.153:8119 + token lowercase + trans_id) que necesita el Content-Auth.
✅ FUNCIÓN A (cifrar el request /slb/v9/live?auth=) — CRACKEADA y verificada (2026-08-09b).
   auth= = base64custom_REQUEST( AES-128-CBC( querystring, key, iv, PKCS7 ) )
   key = d5b1d91ce63c381f339f45f2d932aa50   iv = 19aecdc893ab2aee4dd10e5928f9716f  (FIJOS)
   El REQUEST usa un ALFABETO base64 DISTINTO al de la respuesta (ese era todo el "muro"):
   REQ:  jWB7YtC3n9iXbEkUcJl1VxF4STpQoOIaRmh2M-efAgLwPqGr6uyD5vNsdH_Kz0Z8
   RESP: B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7  (estándar)
   Verificado: decrypt(auth) -> querystring legible; encrypt(querystring) -> auth= idéntico.
   Fn nativa: FUN_003ff160 (0x2ff160) = base64(alfabeto@0x76cab0, encrypt_0x678b14(pt, key=[obj+8])).

============================ EL CIPHER =========================
AES-128-CBC (mbedTLS-style, software; NO usa instrucciones ARM crypto).
  - key = raw MD5 digest (16 bytes) de un source string (se pasa como hex de 32 chars
          y libranger lo hex-decodea: FUN_6796bc).
  - IV  = raw MD5 digest (16 bytes) de otro source.
  - padding PKCS7.
Wrappers en libranger: decrypt=FUN_678cf0, encrypt=FUN_678b14 (mismo esquema);
bloque AES=FUN_5c65d0; key schedule enc=FUN_5b635c, dec=FUN_5bb41c; CBC loop
enc=FUN_5cc3e8, dec=FUN_5cc6a4. base64-custom=FUN_674b20 (alfabeto @0x7c54f0).

Las claves/IV son FIJAS por tipo de mensaje (verificado idénticas entre 2+ sesiones).
Formato de la RESPUESTA: base64custom -> [4-byte header BE = payload_len][AES-CBC ct] -> PKCS7.
Formato del REQUEST: base64custom -> AES-CBC ct (480B, sin header).
"""
import hashlib, base64
from Crypto.Cipher import AES

# ── base64 alfabetos custom de Ranger ───────────────────────────────────────────
# RESPUESTA (Función B): alfabeto estándar de Ranger.
B64_CUSTOM = "B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7"
# REQUEST (Función A): alfabeto DISTINTO (deobfuscado en runtime @ orig 0x76cab0, marcador "req:").
B64_REQUEST = "jWB7YtC3n9iXbEkUcJl1VxF4STpQoOIaRmh2M-efAgLwPqGr6uyD5vNsdH_Kz0Z8"
B64_STD    = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_C2S = {ord(c): ord(s) for c, s in zip(B64_CUSTOM, B64_STD)}
_S2C = {ord(s): ord(c) for c, s in zip(B64_CUSTOM, B64_STD)}
_C2S_REQ = {ord(c): ord(s) for c, s in zip(B64_REQUEST, B64_STD)}
_S2C_REQ = {ord(s): ord(c) for c, s in zip(B64_REQUEST, B64_STD)}

def b64custom_decode(data: str) -> bytes:
    t = bytes(_C2S.get(b, b) for b in data.encode())
    return base64.b64decode(t + b"=" * ((-len(t)) % 4))

def b64custom_encode(raw: bytes) -> str:
    std = base64.b64encode(raw).rstrip(b"=")
    return bytes(_S2C.get(b, b) for b in std).decode()

def b64request_decode(data: str) -> bytes:
    t = bytes(_C2S_REQ.get(b, b) for b in data.encode())
    return base64.b64decode(t + b"=" * ((-len(t)) % 4))

def b64request_encode(raw: bytes) -> str:
    std = base64.b64encode(raw).rstrip(b"=")
    return bytes(_S2C_REQ.get(b, b) for b in std).decode()

# ── AES-128-CBC + PKCS7 ────────────────────────────────────────────────────────
def md5_key(src) -> bytes:
    if isinstance(src, str): src = src.encode()
    return hashlib.md5(src).digest()

def _unpad(b: bytes) -> bytes:
    if b and 1 <= b[-1] <= 16 and b[-b[-1]:] == bytes([b[-1]]) * b[-1]:
        return b[:-b[-1]]
    return b

def _pad(b: bytes) -> bytes:
    n = 16 - (len(b) % 16); return b + bytes([n]) * n

def aes_cbc_decrypt(ct, key, iv, strip_pad=True):
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    return _unpad(pt) if strip_pad else pt

def aes_cbc_encrypt(pt, key, iv, pad=True):
    if pad: pt = _pad(pt)
    return AES.new(key, AES.MODE_CBC, iv).encrypt(pt)

# ── Claves SVS FIJAS (capturadas; idénticas entre sesiones) ─────────────────────
# key/iv = hex string -> bytes.fromhex (== raw MD5 digest de un literal fijo del binario)
SVS_KEYS = {
    # respuesta con {"servers":[{"media_url":"http://149.34.241.153:8119/live/?...token=<lc>&trans_id=..."}]}
    "servers": ("d5b1d91ce63c381f339f45f2d932aa50", "e130e2320d394a7afab21f1b5a1c8251"),
    # respuesta con {"auth":"...main_addr=nvuos...spared_addr=...token=<UPPER>...","err":0}
    "auth":    ("e9ef5394581f7551346dab732a88507f", "71e9775c089d8be699fd850148345231"),
}

def decrypt_svs_response(blob_b64: str, kind="servers") -> bytes:
    """FUNCIÓN B — descifra el blob base64-custom de la respuesta SVS a JSON (bytes).
    kind: 'servers' (respuesta de /slb/v9/live con el endpoint iCDN) o 'auth'."""
    raw = b64custom_decode(blob_b64)
    raw = raw[4:]                                   # quitar header de 4 bytes (len BE)
    kh, ih = SVS_KEYS[kind]
    return aes_cbc_decrypt(raw, bytes.fromhex(kh), bytes.fromhex(ih), strip_pad=True)

# ── FUNCIÓN A: cifrar el request GET /slb/v9/live?auth= (clave/iv FIJOS) ─────────
REQUEST_KEY = "d5b1d91ce63c381f339f45f2d932aa50"
REQUEST_IV  = "19aecdc893ab2aee4dd10e5928f9716f"

def encrypt_svs_request(querystring) -> str:
    """FUNCIÓN A — arma el valor `auth=` del `GET /slb/v9/live?auth=<blob>`.
    querystring: los pares key=value del request (str o bytes), p.ej.
      'spared_addr=...&client_ip=...&media_encrypted=0&app_ver=49902&app_id=com.android.msandroid'
      '&user_id=...&sign_type=cs&dev_id=...&session_id=...&link=icdn&auth_id=..._..._0'
      '&main_addr=nvuos.7r03dh6rph.com&ctrl_type=account&group=<64hex>&expired=<epoch>'
      '&tag=free&check_play_ip=true&token=<32HEX UPPER>'
    Devuelve el blob base64custom-REQUEST listo para la URL."""
    if isinstance(querystring, str):
        querystring = querystring.encode()
    ct = aes_cbc_encrypt(querystring, bytes.fromhex(REQUEST_KEY), bytes.fromhex(REQUEST_IV))
    return b64request_encode(ct)

def decrypt_svs_request(blob_b64: str) -> bytes:
    """Inverso de FUNCIÓN A (para verificar): blob auth= -> querystring plaintext."""
    ct = b64request_decode(blob_b64)
    return aes_cbc_decrypt(ct, bytes.fromhex(REQUEST_KEY), bytes.fromhex(REQUEST_IV), strip_pad=True)

def try_decrypt_svs(blob_b64: str):
    """Prueba ambas claves y con/sin header; devuelve (kind, plaintext) del primero legible."""
    raw = b64custom_decode(blob_b64)
    for kind, (kh, ih) in SVS_KEYS.items():
        for off in (4, 0):
            try:
                pt = aes_cbc_decrypt(raw[off:], bytes.fromhex(kh), bytes.fromhex(ih))
            except Exception:
                continue
            if sum(1 for b in pt if 32 <= b < 127) / max(len(pt), 1) > 0.85:
                return kind, pt
    return None, None

if __name__ == "__main__":
    assert b64custom_decode(b64custom_encode(b"SVS test 12345")) == b"SVS test 12345"
    assert b64request_decode(b64request_encode(b"SVS test 12345")) == b"SVS test 12345"
    assert md5_key("").hex() == "d41d8cd98f00b204e9800998ecf8427e"
    # Función A round-trip
    qs = ("spared_addr=dwgae.srr3ifq00yp.com&client_ip=1.2.3.4&media_encrypted=0&app_ver=49902"
          "&app_id=com.android.msandroid&user_id=631681458&sign_type=cs&dev_id=" + "0"*32 +
          "&session_id=AbCdEf&link=icdn&main_addr=nvuos.7r03dh6rph.com&ctrl_type=account"
          "&group=" + "a"*64 + "&expired=1786258407&tag=free&check_play_ip=true&token=" + "F"*32)
    blob = encrypt_svs_request(qs)
    assert decrypt_svs_request(blob).decode() == qs, "Función A round-trip FAILED"
    print("svs_cipher self-test OK (base64custom + base64request + AES-128-CBC + MD5)")
    print("Función A lista: encrypt_svs_request(querystring) -> blob auth=  (key/iv FIJOS)")
    print("Función B lista: decrypt_svs_response(blob, kind='servers'|'auth')")
