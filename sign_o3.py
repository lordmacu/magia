#!/usr/bin/env python3
"""
sign_o3.py — Genera el `sign2` del header Content-Auth de Magis TV (app netxxus /
"Xuper Hydra"), 100% en Python, SIN depender de la app Android ni del emulador.

FÓRMULA (reverse-engineered, ver DOCS abajo):

    SALT  = b"salt3333=4" + bytes.fromhex("980d0a1532c9c3821708c0")     # constante global
    msg   = f"token={TOKEN}&sign2_method=sign_o3&instance=0&start_moment={MOMENT}".encode() + SALT
    sign2 = tweaked_md5(msg)                                            # hex lowercase de 32 chars

`tweaked_md5` es un MD5 modificado. Desde 2026-08-11 está implementado en **Python puro**
(módulo `tweaked_md5.py`): NO hace falta `libranger-jni.so` ni el paquete `unicorn`.
El tweak resultó ser mínimo: el *message schedule* de la 1ª vuelta, más 4 constantes K
cambiadas (rondas 42/45/54/62); todo lo demás es MD5 de manual.

La clase `TweakedMD5` de este módulo (emulación del .so con Unicorn) se conserva sólo como
ORÁCULO de verificación: `test_tweaked_md5.py` la usa para comprobar que la versión Python
coincide bit a bit con el binario. Importa `unicorn` de forma perezosa, así que su ausencia
no afecta al camino normal.

Uso:
    from sign_o3 import sign_o3
    s = sign_o3("941d98961990d67e249dcd1ac57378c8", 1786229709567)

TOKEN y MOMENT: el token viene del header Content-Auth (lo entrega la API play_live/get_slb
por sesión); MOMENT es el start_moment en milisegundos (time.time()*1000) fresco por request.
"""
import os
import struct
import time

import tweaked_md5


def _load_unicorn():
    """Importa Unicorn SOLO cuando se instancia TweakedMD5 (el oraculo de los tests).

    El camino normal ya no lo necesita: sign_o3() usa tweaked_md5, en Python puro."""
    global Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_ALL, UcError
    global UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_ALL, UcError
    from unicorn.arm64_const import (
        UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
    )

# --- Constantes del algoritmo (extraídas por RE) ---
SALT = b"salt3333=4" + bytes.fromhex("980d0a1532c9c3821708c0")
MD5_IV = bytes.fromhex("0123456789abcdeffedcba9876543210")  # 67452301 efcdab89 98badcfe 10325476
COMPRESS_VADDR = 0x529178   # fcn.529178: compresión MD5-tweak(state_ptr=x0, block_ptr=x1)
RET_MAGIC = 0x30000000

# Ubicación del .so (por defecto junto a este archivo; override con env LIBRANGER_SO)
_DEFAULT_SO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libranger-jni.so")
LIBRANGER_SO = os.environ.get("LIBRANGER_SO", _DEFAULT_SO)


class TweakedMD5:
    """MD5 modificado de Magis TV, emulando la compresión real de libranger-jni.so.

    Mapea los segmentos LOAD del ELF y aplica relocaciones R_AARCH64_RELATIVE (necesarias
    para que resuelvan los saltos calculados del ofuscador OLLVM). Reutiliza una sola
    instancia de Unicorn para que cada compresión sea rápida.
    """

    def __init__(self, so_path=LIBRANGER_SO):
        _load_unicorn()
        if not os.path.exists(so_path):
            raise FileNotFoundError(
                f"No se encontró '{so_path}'. Este binario NO se distribuye en el repo "
                f"(es propietario). Extráelo del APK: lib/arm64-v8a/libranger-jni.so y "
                f"colócalo junto a sign_o3.py (o exporta LIBRANGER_SO=/ruta/al/.so).")
        with open(so_path, "rb") as f:
            self.data = f.read()
        self._parse_segments()
        self._relocs = self._get_relative_relocs()
        self._init_emu()

    def _parse_segments(self):
        d = self.data
        e_phoff = struct.unpack('<Q', d[0x20:0x28])[0]
        e_phentsize = struct.unpack('<H', d[0x36:0x38])[0]
        e_phnum = struct.unpack('<H', d[0x38:0x3a])[0]
        self.segs = []          # (file_off, vaddr, filesz, memsz)
        self._dyn = None        # (file_off, filesz) del PT_DYNAMIC
        for i in range(e_phnum):
            ph = e_phoff + i * e_phentsize
            p_type = struct.unpack('<I', d[ph:ph + 4])[0]
            p_off = struct.unpack('<Q', d[ph + 8:ph + 16])[0]
            p_vaddr = struct.unpack('<Q', d[ph + 16:ph + 24])[0]
            p_filesz = struct.unpack('<Q', d[ph + 32:ph + 40])[0]
            p_memsz = struct.unpack('<Q', d[ph + 40:ph + 48])[0]
            if p_type == 1:      # PT_LOAD
                self.segs.append((p_off, p_vaddr, p_filesz, p_memsz))
            elif p_type == 2:    # PT_DYNAMIC
                self._dyn = (p_off, p_filesz)

    def _vaddr_to_off(self, v):
        for off, vaddr, fsz, _ in self.segs:
            if vaddr <= v < vaddr + fsz:
                return off + (v - vaddr)
        return None

    def _get_relative_relocs(self):
        """Devuelve [(offset, value)] para R_AARCH64_RELATIVE y DT_RELR (base=0)."""
        d = self.data
        doff, dsz = self._dyn
        dyn = {}
        for p in range(doff, doff + dsz, 16):
            tag = struct.unpack('<q', d[p:p + 8])[0]
            val = struct.unpack('<Q', d[p + 8:p + 16])[0]
            if tag == 0:
                break
            dyn[tag] = val
        relocs = []
        # DT_RELA=7, DT_RELASZ=8, DT_RELAENT=9 ; R_AARCH64_RELATIVE=1027
        if 7 in dyn:
            raoff = self._vaddr_to_off(dyn[7])
            rasz = dyn.get(8, 0)
            raent = dyn.get(9, 24)
            for p in range(raoff, raoff + rasz, raent):
                r_off = struct.unpack('<Q', d[p:p + 8])[0]
                r_info = struct.unpack('<Q', d[p + 8:p + 16])[0]
                r_add = struct.unpack('<q', d[p + 16:p + 24])[0]
                if (r_info & 0xffffffff) == 1027:
                    relocs.append((r_off, r_add & 0xffffffffffffffff))
        # DT_RELR=0x23, DT_RELRSZ=0x21 (relocaciones relativas empaquetadas)
        if 0x23 in dyn:
            rr = self._vaddr_to_off(dyn[0x23])
            rrsz = dyn.get(0x21, 0)
            where = 0
            for p in range(rr, rr + rrsz, 8):
                entry = struct.unpack('<Q', d[p:p + 8])[0]
                if entry & 1:
                    bits = entry >> 1
                    addr = where
                    i = 0
                    while bits:
                        if bits & 1:
                            a = addr + i * 8
                            cur = struct.unpack('<Q', d[self._vaddr_to_off(a):self._vaddr_to_off(a) + 8])[0]
                            relocs.append((a, cur))
                        bits >>= 1
                        i += 1
                    where = addr + 63 * 8
                else:
                    where = entry
                    cur = struct.unpack('<Q', d[self._vaddr_to_off(where):self._vaddr_to_off(where) + 8])[0]
                    relocs.append((where, cur))
                    where += 8
        return relocs

    def _init_emu(self):
        mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        top = self._align_up(max(v + m for _, v, _, m in self.segs))
        mu.mem_map(0, top, UC_PROT_ALL)
        for off, vaddr, fsz, _ in self.segs:
            mu.mem_write(vaddr, self.data[off:off + fsz])
        for r_off, val in self._relocs:              # base=0 -> *(off) = value
            try:
                mu.mem_write(r_off, struct.pack('<Q', val & 0xffffffffffffffff))
            except UcError:
                pass
        self.STACK, self.STACKSZ = 0x10000000, 0x200000
        mu.mem_map(self.STACK, self.STACKSZ, UC_PROT_ALL)
        self.SCR = 0x20000000
        mu.mem_map(self.SCR, 0x10000, UC_PROT_ALL)
        self.mu = mu

    @staticmethod
    def _align_up(x, a=0x1000):
        return (x + a - 1) & ~(a - 1)

    def compress(self, state16, block64):
        """Ejecuta fcn.529178(state, block) y devuelve el nuevo estado de 16 bytes."""
        mu = self.mu
        sp, bp = self.SCR, self.SCR + 0x100
        mu.reg_write(UC_ARM64_REG_SP, self.STACK + self.STACKSZ - 0x1000)
        mu.mem_write(sp, state16)
        mu.mem_write(bp, block64)
        mu.reg_write(UC_ARM64_REG_X0, sp)
        mu.reg_write(UC_ARM64_REG_X1, bp)
        mu.reg_write(UC_ARM64_REG_LR, RET_MAGIC)
        mu.emu_start(COMPRESS_VADDR, RET_MAGIC)
        return bytes(mu.mem_read(sp, 16))

    def digest_hex(self, msg: bytes) -> str:
        state = MD5_IV
        i = 0
        while len(msg) - i >= 64:
            state = self.compress(state, msg[i:i + 64])
            i += 64
        rem = msg[i:]
        bitlen = len(msg) * 8
        pad = b'\x80' + b'\x00' * ((56 - (len(rem) + 1)) % 64) + struct.pack('<Q', bitlen)
        final = rem + pad
        j = 0
        while j < len(final):
            state = self.compress(state, final[j:j + 64])
            j += 64
        return state.hex()


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = TweakedMD5()
    return _ENGINE


def sign_o3(token: str, start_moment: int) -> str:
    """Devuelve el `sign2` (32 hex lowercase) para un token de sesión y un start_moment (ms)."""
    msg = (f"token={token}&sign2_method=sign_o3&instance=0"
           f"&start_moment={start_moment}").encode() + SALT
    return tweaked_md5.digest_hex(msg)


def now_moment_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    # Vectores de verificación capturados del binario real (token, moment, sign2 esperado)
    VECTORS = [
        ("941d98961990d67e249dcd1ac57378c8", 1786228951248, "42eda1217c11706f8034f00831f11645"),
        ("941d98961990d67e249dcd1ac57378c8", 1786229028826, "7b7a1751bd8dc9fa4cb38bcc8dd8acb3"),
        ("941d98961990d67e249dcd1ac57378c8", 1786229709567, "0cccdfc85f900a6ee407eedd13003494"),
        ("c3ec544b53a526c59ab677ffbdffa1e0", 1786223278615, "2e055d6f2c0407c82017286e8f4a31ad"),
        ("c3ec544b53a526c59ab677ffbdffa1e0", 1786225491689, "095a0c6ebc25e6570705fd9d16c6b67b"),
    ]
    ok = 0
    for tok, mo, exp in VECTORS:
        got = sign_o3(tok, mo)
        good = got == exp
        ok += good
        print(f"{'OK ' if good else 'XX '} moment={mo} got={got} exp={exp}")
    print(f"\n{ok}/{len(VECTORS)} vectores verificados")
