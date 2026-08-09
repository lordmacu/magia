#!/usr/bin/env python3
"""
svs_capture_request.py — Captura EN CLARO el request HTTP del redirect SVS de Magis TV.

Cómo: el SVS/API va por TLS con la mbedTLS estática de libranger. En un **spawn fresco**
(antes de que el P2SP inunde las funciones TLS), se hookea el `memcpy` DENTRO de
`mbedtls_ssl_write` en `libranger!0x71b4c0` (x1=src=plaintext, x2=len) y se filtra por los
primeros bytes GET/POST/HTTP. Así se ve el request antes de cifrarse.

Resultado esperado (ver SVS_CAMINOS.md):
    GET /slb/v9/live?auth=<blob base64-custom> HTTP/1.1
    Host: nvuos.7r03dh6rph.com   (= main_addr iCDN de get_slb)
    App / App-Version / Content-Type: application/octet-stream / Ranger-Id / User-Agent: Ranger/4.9.4

Uso:  python3 svs_capture_request.py    (Frida necesita Python 3.14; requiere frida + emulador)
"""
import frida
import time

PKG = "com.xuper.netxxus"
MEMCPY_IN_SSL_WRITE = 0x71b4c0   # memcpy(dst=x0, src=x1=plaintext, len=x2) dentro de ssl_write

JS = r"""
var cnt=0, hooked=false;
var install = function(){
  var r=Process.findModuleByName("libranger-jni.so"); if(!r||hooked) return false; hooked=true;
  Interceptor.attach(r.base.add(%d),{onEnter:function(a){
    if(cnt>80) return;
    var src=this.context.x1, len=this.context.x2.toInt32(); if(len<8||len>32768) return;
    var c0,c1,c2; try{ c0=src.readU8(); c1=src.add(1).readU8(); c2=src.add(2).readU8(); }catch(e){ return; }
    // GET / POST / HTTP
    if(!((c0===0x47&&c1===0x45&&c2===0x54)||(c0===0x50&&c1===0x4f&&c2===0x53)||(c0===0x48&&c1===0x54&&c2===0x54))) return;
    cnt++;
    var m=Math.min(len,4000), d=src.readByteArray(m), u=new Uint8Array(d), s="";
    for(var i=0;i<u.length;i++){ s+=(u[i]>=32&&u[i]<127)?String.fromCharCode(u[i]):(u[i]===10?"\n":u[i]===13?"":"."); }
    send({len:len, s:s});
  }});
  send({info:"hooked memcpy@ssl_write"});
  return true;
};
var iv=setInterval(function(){ if(install()) clearInterval(iv); }, 40);
""" % MEMCPY_IN_SSL_WRITE


def main():
    dev = frida.get_usb_device()
    pid = dev.spawn([PKG])
    session = dev.attach(pid)
    script = session.create_script(JS)

    def on_msg(m, d):
        if m.get("type") == "send":
            p = m["payload"]
            if p.get("info"):
                print("[" + p["info"] + "]", flush=True)
            else:
                tag = "SVS" if "/slb" in p["s"][:40] else ("DoH" if "dns-query" in p["s"][:60] else "HTTP")
                print(f"\n===== [{tag}] len={p['len']} =====\n{p['s'][:2200]}", flush=True)
        elif m.get("type") == "error":
            print("ERR", m.get("description"), flush=True)

    script.on("message", on_msg)
    script.load()
    dev.resume(pid)
    print("SPAWN; esperando el SVS temprano (~10-40s)...", flush=True)
    time.sleep(45)
    print("FIN", flush=True)


if __name__ == "__main__":
    main()
