#!/usr/bin/env python3
"""
svs_replay.py — Replica el request del SVS desde Python y decodifica los blobs base64-custom.

Tomá el request capturado con svs_capture_request.py (GET /slb/v9/live?auth=<blob> a nvuos...),
pegá el path + Ranger-Id abajo, y este script lo re-envía por TLS y muestra la respuesta.
Verificado: devuelve 200 con otro blob base64-custom (512 bytes AES tras decodificar).

El auth= del request y la respuesta son base64-custom de AES cifrado (ver SVS_CAMINOS.md):
falta la clave AES + estructura del plaintext para generarlo/descifrarlo sin la app.
"""
import base64
import ssl
import urllib.request

# --- Pegá acá lo capturado (path completo con ?auth=... y el Ranger-Id) ---
SVS_HOST = "nvuos.7r03dh6rph.com"          # = main_addr del CDN icdn en get_slb (varía por sesión)
SVS_PATH = "/slb/v9/live?auth=PEGAR_BLOB_AQUI"
RANGER_ID = "PEGAR_RANGER_ID_AQUI"

# alfabeto base64-custom de Ranger (custom -> estándar, luego b64decode)
CUSTOM = "B8oOvNYtn9RPijWXbcJqGyD5Eklmh21V_efAgLC3wxF4STpQr6usdHM-Kz0IaUZ7"
STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def custom_b64_decode(s: str) -> bytes:
    s = s.rstrip("=")
    std = s.translate(str.maketrans(CUSTOM, STD))
    pad = (-len(std)) % 4
    return base64.b64decode(std + "=" * pad)


def replay():
    url = f"https://{SVS_HOST}{SVS_PATH}"
    headers = {
        "Accept": "*/*",
        "App": "com.android.msandroid",
        "App-Version": "49902",
        "Content-Type": "application/octet-stream",
        "Ranger-Id": RANGER_ID,
        "User-Agent": "Ranger/4.9.4-17294ac0",
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=12, context=ctx)
    body = r.read()
    print("STATUS:", r.status, "| resp len:", len(body))
    resp_blob = body.decode("ascii", "replace").strip()
    print("resp blob:", resp_blob[:80], "...")
    dec = custom_b64_decode(resp_blob)
    printable = sum(1 for c in dec if 32 <= c < 127)
    print(f"decoded: {len(dec)} bytes | {printable*100//max(len(dec),1)}% printable (bajo = AES cifrado)")
    print("hex[:48]:", dec[:48].hex())


if __name__ == "__main__":
    replay()
