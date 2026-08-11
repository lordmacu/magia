#!/usr/bin/env python3
"""Recuperacion de sesion en IPTVClient, sin tocar la red.

Se sustituye SOLO el transporte (`_call_once`), que es la frontera con el servidor;
la logica de decision (que codigos son recuperables, por que via y para que tipo de
sesion) es la real.
"""
import unittest

import iptv_client


class _FakeServer(iptv_client.IPTVClient):
    """Responde el codigo indicado hasta que cambie el userToken, y despues OK."""

    def __init__(self, code, auth_mode, **kw):
        self.llamadas = []
        self.reautenticaciones = 0
        self._codigo = code
        self.user_id = "1"
        self.user_token = "TOKEN_VIEJO"
        self.portal = "masnew"
        self.device = {}
        self._auth_mode = auth_mode
        self._creds = ("u", "p", "2", "1", "") if auth_mode == "account" else None
        self._reauthing = False

    def _call_once(self, path, bean=None, base_fields=True):
        self.llamadas.append((path, self.user_token))
        if self.user_token == "TOKEN_VIEJO":
            return {"_error": self._codigo, "_msg": "simulado", "_path": path}
        return {"ok": True, "_path": path}

    def activate(self):
        self.reautenticaciones += 1
        self.user_token = "TOKEN_NUEVO"
        return {"userId": "1", "userToken": self.user_token}

    def login(self, *a, **kw):
        self.reautenticaciones += 1
        self.user_token = "TOKEN_NUEVO"
        return {"userId": "1", "userToken": self.user_token}


class RecuperacionDeSesion(unittest.TestCase):
    def test_device_se_recupera_de_sesion_expirada(self):
        c = _FakeServer("aaa100028", "device")
        r = c.call("v3/searchByName", {"v": 1})
        self.assertEqual(r.get("ok"), True, "deberia reintentar con el token nuevo")
        self.assertEqual(c.reautenticaciones, 1)

    def test_device_se_recupera_de_sesion_tomada_por_otro_dispositivo(self):
        """aaa100083 en device/free: re-activar equivale a reiniciar el CLI."""
        c = _FakeServer("aaa100083", "device")
        r = c.call("v4/startPlayLive", {"channelCode": "x"})
        self.assertEqual(r.get("ok"), True, "en free deberia re-activarse y reintentar")
        self.assertEqual(c.reautenticaciones, 1)

    def test_cuenta_NO_se_pelea_la_sesion_con_el_otro_dispositivo(self):
        """Con una cuenta real, re-loguear expulsaria al otro dispositivo: no se hace."""
        c = _FakeServer("aaa100083", "account")
        r = c.call("v4/startPlayLive", {"channelCode": "x"})
        self.assertEqual(r.get("_error"), "aaa100083", "debe devolver el error, no re-loguear")
        self.assertEqual(c.reautenticaciones, 0)

    def test_sesion_manual_nunca_se_renueva(self):
        c = _FakeServer("aaa100028", "manual")
        r = c.call("v3/searchByName", {"v": 1})
        self.assertEqual(r.get("_error"), "aaa100028")
        self.assertEqual(c.reautenticaciones, 0)

    def test_no_reintenta_en_las_rutas_que_establecen_sesion(self):
        c = _FakeServer("aaa100028", "device")
        r = c.call("v8/active", {}, base_fields=False)
        self.assertEqual(r.get("_error"), "aaa100028")
        self.assertEqual(c.reautenticaciones, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
