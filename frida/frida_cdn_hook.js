/*
 * frida_cdn_hook.js — captura CDN URLs del proxy Titan/Ranger
 *
 * Uso: frida -D emulator-5554 -f com.xuper.netxxus -l frida_cdn_hook.js
 */

var TAG = "[CDN]";
var captured = [];

// ─── Anti-Frida bypass ───
// La app detecta Frida por threads que escuchan en puertos típicos.
// Parcheamos la detección antes de que corra.
(function bypassAntifrida() {
    // Hook pthread_create para bloquear threads de detección
    try {
        var pthread_create = Module.findExportByName("libc.so", "pthread_create");
        Interceptor.attach(pthread_create, {
            onEnter: function (args) {
                var fn = args[2];
                // Si el start_routine apunta a una zona sospechosa, la dejamos pasar
                // pero podemos loguear para debug
            }
        });
    } catch (e) {}

    // Hook openat/open para detectar lectura de /proc/self/maps (otra técnica anti-Frida)
    try {
        var openat = Module.findExportByName("libc.so", "openat");
        if (openat) {
            Interceptor.attach(openat, {
                onEnter: function (args) {
                    try {
                        var path = args[1].readCString();
                        if (path && (path.indexOf("frida") >= 0 || path.indexOf("gadget") >= 0)) {
                            console.log(TAG + " BLOCKED openat: " + path);
                            args[1] = Memory.allocUtf8String("/dev/null");
                        }
                    } catch (e) {}
                }
            });
        }
    } catch (e) {}

    // Bloquear strstr buscando "frida" en /proc/self/maps
    try {
        var strstr = Module.findExportByName("libc.so", "strstr");
        Interceptor.attach(strstr, {
            onEnter: function (args) {
                try {
                    var needle = args[1].readCString();
                    if (needle && (needle === "frida" || needle === "gadget" || needle === "LIBFRIDA")) {
                        this._block = true;
                    }
                } catch (e) {}
            },
            onLeave: function (retval) {
                if (this._block) {
                    retval.replace(ptr(0)); // return NULL = not found
                }
            }
        });
    } catch (e) {}
})();

// ─── 1. Hook Java: NativeJni.Call() ───
function hookRanger() {
    Java.perform(function () {
        try {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);
                var dominated = ["PrepareProgram", "SetMedia", "SetEntries", "SetEnv"];
                if (dominated.indexOf(method) >= 0) {
                    console.log("\n" + TAG + " ══════ Ranger." + method + " ══════");
                    console.log(TAG + " IN:  " + body);
                    if (result) console.log(TAG + " OUT: " + result.substring(0, 1000));
                }
                return result;
            };
            console.log(TAG + " Ranger.Call hooked");
        } catch (e) {
            console.log(TAG + " Ranger hook err: " + e);
        }
    });
}

// ─── 2. Hook connect() — detecta IPs de CDN ───
function hookConnect() {
    try {
        var connectFn = Module.findExportByName("libc.so", "connect");
        Interceptor.attach(connectFn, {
            onEnter: function (args) {
                try {
                    var sa = args[1];
                    var family = Memory.readU16(sa);
                    if (family === 2) { // AF_INET
                        var b2 = Memory.readU8(sa.add(2));
                        var b3 = Memory.readU8(sa.add(3));
                        var port = (b2 << 8) | b3;
                        var ip = Memory.readU8(sa.add(4)) + "." +
                                 Memory.readU8(sa.add(5)) + "." +
                                 Memory.readU8(sa.add(6)) + "." +
                                 Memory.readU8(sa.add(7));
                        if ((port === 80 || port === 443) && ip !== "127.0.0.1" && ip !== "10.0.2.2") {
                            console.log(TAG + " connect -> " + ip + ":" + port + " fd=" + args[0].toInt32());
                        }
                    }
                } catch (e) {}
            }
        });
        console.log(TAG + " connect() hooked");
    } catch (e) {
        console.log(TAG + " connect hook err: " + e);
    }
}

// ─── 3. Hook send/write — captura HTTP en crudo ───
function hookIO() {
    ["sendto", "send", "write"].forEach(function (fname) {
        try {
            var fn = Module.findExportByName("libc.so", fname);
            if (!fn) return;
            Interceptor.attach(fn, {
                onEnter: function (args) {
                    var len = args[2].toInt32();
                    if (len < 20 || len > 50000) return;
                    try {
                        var buf = args[1];
                        // Peek first 4 bytes to check for HTTP methods
                        var h = Memory.readU32(buf);
                        // GET  = 0x20544547, POST = 0x54534f50, HEAD = 0x44414548
                        if (h === 0x20544547 || h === 0x54534f50 || h === 0x44414548) {
                            var data = Memory.readUtf8String(buf, Math.min(len, 3000));
                            console.log("\n" + TAG + " ══════ " + fname + " HTTP fd=" + args[0].toInt32() + " len=" + len + " ══════");
                            console.log(data);
                        }
                    } catch (e) {}
                }
            });
            console.log(TAG + " " + fname + "() hooked");
        } catch (e) {}
    });
}

// ─── 4. Hook SSL_write — captura HTTPS requests ───
function hookSSL() {
    // Android usa BoringSSL, buscar en todos los módulos
    var modules = Process.enumerateModules();
    var sslMod = null;
    for (var i = 0; i < modules.length; i++) {
        if (modules[i].name.indexOf("libssl") >= 0) {
            sslMod = modules[i].name;
            break;
        }
    }
    if (!sslMod) {
        console.log(TAG + " No SSL module found");
        return;
    }

    try {
        var ssl_write = Module.findExportByName(sslMod, "SSL_write");
        if (!ssl_write) { console.log(TAG + " SSL_write not in " + sslMod); return; }

        Interceptor.attach(ssl_write, {
            onEnter: function (args) {
                var len = args[2].toInt32();
                if (len < 20 || len > 50000) return;
                try {
                    var h = Memory.readU32(args[1]);
                    if (h === 0x20544547 || h === 0x54534f50 || h === 0x44414548) {
                        var data = Memory.readUtf8String(args[1], Math.min(len, 3000));
                        console.log("\n" + TAG + " ══════ SSL_write len=" + len + " ══════");
                        console.log(data);
                        captured.push(data);
                    }
                } catch (e) {}
            }
        });
        console.log(TAG + " SSL_write hooked via " + sslMod);
    } catch (e) {
        console.log(TAG + " SSL hook err: " + e);
    }
}

// ─── 5. Hook OkHttp (para la descarga) ───
function hookOkHttp() {
    Java.perform(function () {
        try {
            // El app usa OkHttp 3.x (okhttp3.RealCall)
            var classes = ["okhttp3.RealCall", "okhttp3.internal.connection.RealCall"];
            classes.forEach(function (cls) {
                try {
                    var RealCall = Java.use(cls);
                    RealCall.execute.implementation = function () {
                        var req = this.request();
                        var url = req.url().toString();
                        console.log("\n" + TAG + " ══════ OkHttp " + req.method() + " ══════");
                        console.log(TAG + " URL: " + url);
                        var hdrs = req.headers();
                        for (var i = 0; i < hdrs.size(); i++) {
                            console.log(TAG + " " + hdrs.name(i) + ": " + hdrs.value(i));
                        }
                        var resp = this.execute();
                        console.log(TAG + " -> " + resp.code());
                        return resp;
                    };
                    console.log(TAG + " " + cls + ".execute hooked");
                } catch (e) {}
            });
        } catch (e) {}
    });
}

// ─── GO ───
console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " CDN URL capture — play a video now!");
console.log(TAG + " ════════════════════════════════════");
hookRanger();
hookConnect();
hookIO();
hookSSL();
hookOkHttp();
console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " All hooks ready. Waiting for play...");
console.log(TAG + " ════════════════════════════════════");
