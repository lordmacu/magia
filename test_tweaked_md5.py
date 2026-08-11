#!/usr/bin/env python3
"""Equivalencia entre el MD5-tweak en Python puro y la emulacion Unicorn del .so.

La emulacion (sign_o3.TweakedMD5) es el ORACULO: es la funcion real del binario.
Si estos tests pasan, tweaked_md5.py puede reemplazar al .so sin cambiar un bit.

Requiere libranger-jni.so para correr (es quien hace de oraculo); sin el se saltan.
"""
import os
import random
import struct
import sys
import unittest

import tweaked_md5

try:
    from sign_o3 import TweakedMD5
    _ORACLE = TweakedMD5()
except Exception as _e:                                    # sin .so / sin unicorn
    _ORACLE = None
    _WHY = str(_e)


@unittest.skipIf(_ORACLE is None, "hace falta libranger-jni.so + unicorn como oraculo")
class CompressMatchesNativeOracle(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(20260811)

    def test_compress_matches_oracle_on_random_blocks(self):
        for i in range(200):
            state = bytes(self.rng.randrange(256) for _ in range(16))
            block = bytes(self.rng.randrange(256) for _ in range(64))
            self.assertEqual(
                tweaked_md5.compress(state, block).hex(),
                _ORACLE.compress(state, block).hex(),
                f"difiere en el caso aleatorio #{i}",
            )

    def test_compress_matches_oracle_on_edge_states(self):
        edges = [b"\x00" * 16, b"\xff" * 16,
                 bytes.fromhex("0123456789abcdeffedcba9876543210")]   # el IV real
        blocks = [b"\x00" * 64, b"\xff" * 64,
                  bytes(range(64)),
                  b"\x80" + b"\x00" * 55 + struct.pack("<Q", 0)]
        for st in edges:
            for bl in blocks:
                self.assertEqual(
                    tweaked_md5.compress(st, bl).hex(),
                    _ORACLE.compress(st, bl).hex(),
                    f"difiere con state={st.hex()} block={bl.hex()[:32]}...",
                )


@unittest.skipIf(_ORACLE is None, "hace falta libranger-jni.so + unicorn como oraculo")
class DigestMatchesNativeOracle(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(11235)

    def test_digest_matches_oracle_on_padding_boundaries(self):
        # 55/56 y 63/64 son donde el padding MD5 cambia de bloque
        for n in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 128, 200]:
            msg = bytes(self.rng.randrange(256) for _ in range(n))
            self.assertEqual(
                tweaked_md5.digest_hex(msg),
                _ORACLE.digest_hex(msg),
                f"difiere con mensaje de {n} bytes",
            )

    def test_digest_matches_oracle_on_random_messages(self):
        for i in range(60):
            n = self.rng.randrange(0, 300)
            msg = bytes(self.rng.randrange(256) for _ in range(n))
            self.assertEqual(
                tweaked_md5.digest_hex(msg),
                _ORACLE.digest_hex(msg),
                f"difiere en el mensaje aleatorio #{i} ({n} bytes)",
            )


class SignO3StaysIdentical(unittest.TestCase):
    """Valores fijados con la implementacion nativa (.so + Unicorn) antes de migrar.

    No dependen del oraculo: corren aunque no este el .so, que es justamente el punto
    -- si manana sign_o3 deja de coincidir con estos, la migracion rompio algo."""

    GOLDEN = [
        ("941d98961990d67e249dcd1ac57378c8", 1786228951248, "42eda1217c11706f8034f00831f11645"),
        ("941d98961990d67e249dcd1ac57378c8", 1786229028826, "7b7a1751bd8dc9fa4cb38bcc8dd8acb3"),
        ("941d98961990d67e249dcd1ac57378c8", 1786229709567, "0cccdfc85f900a6ee407eedd13003494"),
        ("c3ec544b53a526c59ab677ffbdffa1e0", 1786223278615, "2e055d6f2c0407c82017286e8f4a31ad"),
        ("c3ec544b53a526c59ab677ffbdffa1e0", 1786225491689, "095a0c6ebc25e6570705fd9d16c6b67b"),
    ]

    def test_sign_o3_reproduces_native_signatures(self):
        from sign_o3 import sign_o3
        for token, moment, expected in self.GOLDEN:
            self.assertEqual(sign_o3(token, moment), expected,
                             f"sign2 cambio para token={token} moment={moment}")

    def test_sign_o3_needs_no_native_dependency(self):
        """sign_o3 debe importarse y firmar sin unicorn ni el .so cargados."""
        import subprocess
        code = (
            "import sys;"
            "sys.modules['unicorn'] = None;"          # simula unicorn ausente
            "import sign_o3;"
            "print(sign_o3.sign_o3('941d98961990d67e249dcd1ac57378c8', 1786229709567))"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(r.returncode, 0, f"fallo sin unicorn:\n{r.stderr[-800:]}")
        self.assertEqual(r.stdout.strip(), "0cccdfc85f900a6ee407eedd13003494")


if __name__ == "__main__":
    unittest.main(verbosity=2)
