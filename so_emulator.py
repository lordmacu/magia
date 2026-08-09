#!/usr/bin/env python3
"""
so_emulator.py — Toolkit reutilizable para CRACKEAR funciones nativas ARM64 emulándolas
con Unicorn Engine (el método con el que resolvimos `sign_o3` de Magis TV).

Idea: en vez de reimplementar a mano una función ofuscada (OLLVM, MD5-tweak, cifrados
propietarios, firmas, etc.), se EMULA la función real del `.so`. Se mapean los segmentos
del ELF, se aplican las relocaciones (imprescindible para que resuelvan los saltos
calculados del ofuscador) y se ejecuta la función con Unicorn dándole tus inputs.

Uso rápido:
    from so_emulator import SoEmulator
    emu = SoEmulator("libranger-jni.so")
    # emular fcn(state_ptr=x0, block_ptr=x1) -> escribe 16 bytes en state_ptr
    state = emu.alloc(16, b"\\x01\\x23...")
    block = emu.alloc(64, b"token=...")
    emu.call(0x529178, [state, block])
    out = emu.read(state, 16)

Para DESCUBRIR (instrumentar) cómo funciona una función:
    emu.call(0x529178, [state, block],
             on_code=lambda uc,a,sz: ...,           # hook por instrucción
             on_read=lambda uc,acc,a,sz,v: ...)      # hook de lectura de memoria
    # o usar los helpers: emu.trace_calls(...), emu.watch_reads(range), emu.capture_at(addrs, regs)

Requisitos: pip install unicorn.  Solo necesita el archivo .so (ARM64) — nada de Android/adb/Frida.
"""
import struct
from unicorn import (
    Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_PROT_ALL, UcError,
    UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_BLOCK,
)
from unicorn import arm64_const as A

# registros x0..x30 y w0..w30 (nombres -> constantes Unicorn)
_XREGS = {i: getattr(A, f"UC_ARM64_REG_X{i}") for i in range(31)}
_WREGS = {i: getattr(A, f"UC_ARM64_REG_W{i}") for i in range(31)}
_SP = A.UC_ARM64_REG_SP
_LR = A.UC_ARM64_REG_LR
_PC = A.UC_ARM64_REG_PC

R_AARCH64_RELATIVE = 1027
DT_RELA, DT_RELASZ, DT_RELAENT = 7, 8, 9
DT_RELR, DT_RELRSZ = 0x23, 0x21


class SoEmulator:
    """Emula funciones de un .so ARM64 mapeando sus segmentos + relocaciones."""

    def __init__(self, so_path, stack_base=0x10000000, stack_size=0x200000,
                 scratch_base=0x20000000, scratch_size=0x100000, ret_magic=0x30000000):
        with open(so_path, "rb") as f:
            self.data = f.read()
        self.stack_base, self.stack_size = stack_base, stack_size
        self.scratch_base, self.scratch_size = scratch_base, scratch_size
        self.ret_magic = ret_magic
        self._parse_segments()
        self._relocs = self._get_relative_relocs()
        self._map()

    # ---------- ELF ----------
    def _parse_segments(self):
        d = self.data
        assert d[:4] == b"\x7fELF", "no es un ELF"
        e_phoff = struct.unpack('<Q', d[0x20:0x28])[0]
        e_phentsize = struct.unpack('<H', d[0x36:0x38])[0]
        e_phnum = struct.unpack('<H', d[0x38:0x3a])[0]
        self.segs, self._dyn = [], None
        for i in range(e_phnum):
            ph = e_phoff + i * e_phentsize
            p_type = struct.unpack('<I', d[ph:ph + 4])[0]
            p_off = struct.unpack('<Q', d[ph + 8:ph + 16])[0]
            p_vaddr = struct.unpack('<Q', d[ph + 16:ph + 24])[0]
            p_filesz = struct.unpack('<Q', d[ph + 32:ph + 40])[0]
            p_memsz = struct.unpack('<Q', d[ph + 40:ph + 48])[0]
            if p_type == 1:            # PT_LOAD
                self.segs.append((p_off, p_vaddr, p_filesz, p_memsz))
            elif p_type == 2:          # PT_DYNAMIC
                self._dyn = (p_off, p_filesz)

    def _v2o(self, v):
        for off, va, fsz, _ in self.segs:
            if va <= v < va + fsz:
                return off + (v - va)
        return None

    def _get_relative_relocs(self):
        """R_AARCH64_RELATIVE + DT_RELR (base=0). Sin esto, los `br xN` del OLLVM van a 0x0."""
        if not self._dyn:
            return []
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
        if DT_RELA in dyn:
            ra = self._v2o(dyn[DT_RELA]); sz = dyn.get(DT_RELASZ, 0); ent = dyn.get(DT_RELAENT, 24)
            for p in range(ra, ra + sz, ent):
                r_off = struct.unpack('<Q', d[p:p + 8])[0]
                r_info = struct.unpack('<Q', d[p + 8:p + 16])[0]
                r_add = struct.unpack('<q', d[p + 16:p + 24])[0]
                if (r_info & 0xffffffff) == R_AARCH64_RELATIVE:
                    relocs.append((r_off, r_add & 0xffffffffffffffff))
        if DT_RELR in dyn:
            rr = self._v2o(dyn[DT_RELR]); sz = dyn.get(DT_RELRSZ, 0); where = 0
            for p in range(rr, rr + sz, 8):
                entry = struct.unpack('<Q', d[p:p + 8])[0]
                if entry & 1:
                    bits = entry >> 1; addr = where; i = 0
                    while bits:
                        if bits & 1:
                            a = addr + i * 8
                            cur = struct.unpack('<Q', d[self._v2o(a):self._v2o(a) + 8])[0]
                            relocs.append((a, cur))
                        bits >>= 1; i += 1
                    where = addr + 63 * 8
                else:
                    where = entry
                    cur = struct.unpack('<Q', d[self._v2o(where):self._v2o(where) + 8])[0]
                    relocs.append((where, cur)); where += 8
        return relocs

    # ---------- memoria ----------
    @staticmethod
    def _align_up(x, a=0x1000):
        return (x + a - 1) & ~(a - 1)

    def _map(self):
        mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        top = self._align_up(max(v + m for _, v, _, m in self.segs))
        mu.mem_map(0, top, UC_PROT_ALL)
        for off, va, fsz, _ in self.segs:
            mu.mem_write(va, self.data[off:off + fsz])
        for r_off, val in self._relocs:
            try:
                mu.mem_write(r_off, struct.pack('<Q', val & 0xffffffffffffffff))
            except UcError:
                pass
        mu.mem_map(self.stack_base, self.stack_size, UC_PROT_ALL)
        mu.mem_map(self.scratch_base, self.scratch_size, UC_PROT_ALL)
        self.mu = mu
        self._scratch_ptr = self.scratch_base

    def alloc(self, size, data=b""):
        """Reserva `size` bytes en el scratch y opcionalmente los inicializa. Devuelve el puntero."""
        p = self._scratch_ptr
        self._scratch_ptr = self._align_up(p + max(size, len(data)), 16)
        if data:
            self.mu.mem_write(p, data)
        return p

    def read(self, ptr, n):
        return bytes(self.mu.mem_read(ptr, n))

    def write(self, ptr, data):
        self.mu.mem_write(ptr, data)

    def reset_scratch(self):
        self._scratch_ptr = self.scratch_base

    # ---------- ejecución ----------
    def call(self, func_vaddr, args=None, on_code=None, on_read=None, on_write=None,
             on_block=None, timeout_insns=0):
        """Ejecuta func_vaddr(args...). args = lista de enteros (van a x0,x1,x2,...).
        Devuelve x0. Los hooks on_* permiten instrumentar (descubrir). Reutiliza el mapeo."""
        mu = self.mu
        args = args or []
        mu.reg_write(_SP, self.stack_base + self.stack_size - 0x1000)
        for i, v in enumerate(args[:8]):
            mu.reg_write(_XREGS[i], v & 0xffffffffffffffff)
        mu.reg_write(_LR, self.ret_magic)
        handles = []
        if on_code:  handles.append(mu.hook_add(UC_HOOK_CODE, on_code))
        if on_read:  handles.append(mu.hook_add(UC_HOOK_MEM_READ, on_read))
        if on_write: handles.append(mu.hook_add(UC_HOOK_MEM_WRITE, on_write))
        if on_block: handles.append(mu.hook_add(UC_HOOK_BLOCK, on_block))
        try:
            mu.emu_start(func_vaddr, self.ret_magic, count=timeout_insns)
        finally:
            for h in handles:
                try: mu.hook_del(h)
                except UcError: pass
        return mu.reg_read(_XREGS[0])

    def reg(self, i, w=False):
        return self.mu.reg_read(_WREGS[i] if w else _XREGS[i])

    # ---------- helpers de DESCUBRIMIENTO ----------
    def trace_calls(self, func_vaddr, args=None):
        """Devuelve la lista de destinos BL/BLR (llamadas) dentro del módulo, en orden."""
        base_top = max(v + m for _, v, _, m in self.segs)
        calls = []
        def hook(uc, addr, size, ud):
            code = uc.mem_read(addr, 4)
            instr = struct.unpack('<I', code)[0]
            # BL: 100101 imm26 ; BLR: 1101011000111111000000 Rn 00000
            if (instr & 0xFC000000) == 0x94000000:
                imm = instr & 0x03FFFFFF
                if imm & 0x02000000: imm -= 0x04000000
                calls.append(addr + imm * 4)
            elif (instr & 0xFFFFFC1F) == 0xD63F0000:
                rn = (instr >> 5) & 0x1F
                calls.append(uc.reg_read(_XREGS[rn]))
        self.call(func_vaddr, args, on_code=hook)
        return calls

    def watch_reads(self, func_vaddr, args=None, lo=None, hi=None):
        """Registra (pc, addr, size) de lecturas de memoria en [lo,hi). Útil para ver qué datos
        consume la función (tablas, constantes, el buffer de entrada)."""
        hits = []
        def hook(uc, access, addr, size, value, ud):
            if lo is None or (lo <= addr < hi):
                hits.append((uc.reg_read(_PC), addr, size))
        self.call(func_vaddr, args, on_read=hook)
        return hits

    def capture_at(self, func_vaddr, addrs, regs=range(31), args=None, as_word=True):
        """En cada dirección de `addrs`, captura el valor de los registros indicados.
        Devuelve lista de (pc, {reg: val}) en orden de ejecución. Así extrajimos el schedule
        del MD5-tweak leyendo el operando de cada `ror`."""
        addrs = set(addrs)
        out = []
        def hook(uc, addr, size, ud):
            if addr in addrs:
                snap = {r: uc.reg_read(_WREGS[r] if as_word else _XREGS[r]) for r in regs}
                out.append((addr, snap))
        self.call(func_vaddr, args, on_code=hook)
        return out


# ─────────────────────────  EJEMPLO / self-test  ─────────────────────────
if __name__ == "__main__":
    import os
    so = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libranger-jni.so")
    emu = SoEmulator(so)
    print(f"[so_emulator] cargado {so}")
    print(f"  segmentos: {len(emu.segs)} | relocaciones: {len(emu._relocs)}")

    # Ejemplo real: la compresión MD5-tweak de sign_o3 en 0x529178(state, block) -> state'
    IV = bytes.fromhex("0123456789abcdeffedcba9876543210")
    block = b"token=941d98961990d67e249dcd1ac57378c8&sign2_method=sign_o3&inst"
    st = emu.alloc(16, IV)
    bl = emu.alloc(64, block)
    emu.call(0x529178, [st, bl])
    out = emu.read(st, 16).hex()
    exp = "e928545dee8c87ec8966addbdfd31787"
    print(f"  emular 0x529178: {out}  {'OK' if out == exp else 'FAIL (esperado ' + exp + ')'}")

    # Ejemplo de descubrimiento: qué funciones llama
    emu.reset_scratch()
    st = emu.alloc(16, IV); bl = emu.alloc(64, block)
    calls = emu.trace_calls(0x529178, [st, bl])
    inmod = sorted({c for c in calls if c < max(v + m for _, v, _, m in emu.segs)})
    print(f"  0x529178 llama a: {[hex(c) for c in inmod][:6]}")
