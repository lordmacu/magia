/*
 * frida_cdn_hook2.js — captura HTTP/HTTPS real del proxy Ranger
 * Foco: hookear a nivel nativo DESPUÉS de que los módulos cargan.
 */

var TAG = "[CDN]";

// ─── Anti-Frida ───
(function () {
    try {
        var strstr = Module.getExportByName("libc.so", "strstr");
        Interceptor.attach(strstr, {
            onEnter: function (args) {
                try {
                    var s = args[1].readCString();
                    if (s && (s === "frida" || s === "gadget" || s === "LIBFRIDA" || s === "gum-js-loop" || s === "linjector")) {
                        this._block = true;
                    }
                } catch (e) {}
            },
            onLeave: function (retval) {
                if (this._block) retval.replace(ptr(0));
            }
        });
    } catch (e) {}

    try {
        var openat = Module.getExportByName("libc.so", "openat");
        Interceptor.attach(openat, {
            onEnter: function (args) {
                try {
                    var p = args[1].readCString();
                    if (p && p.indexOf("frida") >= 0) args[1] = Memory.allocUtf8String("/dev/null");
                } catch (e) {}
            }
        });
    } catch (e) {}
})();

// ─── Ranger Java hooks (estos funcionaron) ───
function hookRanger() {
    Java.perform(function () {
        try {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);
                if (method === "PrepareProgram" || method === "SetMedia" || method === "SetEntries") {
                    console.log("\n" + TAG + " ██ Ranger." + method + " ██");
                    console.log(TAG + " IN:  " + body);
                    if (result) console.log(TAG + " OUT: " + (result.length > 1000 ? result.substring(0, 1000) + "..." : result));
                }
                if (method === "GetStatus") {
                    try {
                        var res = JSON.parse(result);
                        if (res.res) {
                            var status = JSON.parse(res.res);
                            if (status.play_url) {
                                console.log("\n" + TAG + " ██ PLAY_URL FOUND ██");
                                console.log(TAG + " " + status.play_url);
                            }
                        }
                    } catch (e) {}
                }
                return result;
            };
            console.log(TAG + " Ranger hooked");
        } catch (e) {
            console.log(TAG + " Ranger err: " + e);
        }
    });
}

// ─── Delay native hooks until libs are loaded ───
function hookNative() {
    // Hook connect, SSL_write, etc. after a delay
    // Use Module.getExportByName which throws on failure (vs findExportByName which returns null)
    try {
        var connect_ptr = Module.getExportByName("libc.so", "connect");
        Interceptor.attach(connect_ptr, {
            onEnter: function (args) {
                try {
                    var sa = args[1];
                    var fam = sa.readU16();
                    if (fam === 2) {
                        var p1 = sa.add(2).readU8();
                        var p2 = sa.add(3).readU8();
                        var port = (p1 << 8) | p2;
                        var ip = sa.add(4).readU8() + "." + sa.add(5).readU8() + "." + sa.add(6).readU8() + "." + sa.add(7).readU8();
                        if ((port === 80 || port === 443 || port === 18084 || port === 8080) && ip !== "127.0.0.1" && ip !== "10.0.2.2" && ip !== "10.0.2.3") {
                            console.log(TAG + " connect -> " + ip + ":" + port);
                        }
                    }
                } catch (e) {}
            }
        });
        console.log(TAG + " connect hooked");
    } catch (e) {
        console.log(TAG + " connect err: " + e);
    }

    // SSL_write hook
    try {
        // En Android, BoringSSL está en /system/lib64/libssl.so o en el app
        var mods = Process.enumerateModules();
        var sslMods = mods.filter(function (m) { return m.name.indexOf("ssl") >= 0; });
        console.log(TAG + " SSL modules: " + sslMods.map(function (m) { return m.name; }).join(", "));

        sslMods.forEach(function (mod) {
            try {
                var sw = Module.getExportByName(mod.name, "SSL_write");
                Interceptor.attach(sw, {
                    onEnter: function (args) {
                        var len = args[2].toInt32();
                        if (len < 20 || len > 100000) return;
                        try {
                            var peek = args[1].readCString(4);
                            if (peek === "GET " || peek === "POST" || peek === "HEAD") {
                                var data = args[1].readCString(Math.min(len, 4000));
                                console.log("\n" + TAG + " ██ SSL_write " + len + "b ██");
                                console.log(data);
                            }
                        } catch (e) {}
                    }
                });
                console.log(TAG + " SSL_write hooked via " + mod.name);
            } catch (e) {}
        });
    } catch (e) {
        console.log(TAG + " SSL err: " + e);
    }

    // Plain HTTP send/write
    try {
        var send_ptr = Module.getExportByName("libc.so", "sendto");
        Interceptor.attach(send_ptr, {
            onEnter: function (args) {
                var len = args[2].toInt32();
                if (len < 20 || len > 100000) return;
                try {
                    var peek = args[1].readCString(4);
                    if (peek === "GET " || peek === "POST" || peek === "HEAD") {
                        var data = args[1].readCString(Math.min(len, 4000));
                        console.log("\n" + TAG + " ██ sendto HTTP " + len + "b ██");
                        console.log(data);
                    }
                } catch (e) {}
            }
        });
        console.log(TAG + " sendto hooked");
    } catch (e) {
        console.log(TAG + " sendto err: " + e);
    }
}

// ─── OkHttp ───
function hookOkHttp() {
    Java.perform(function () {
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function () {
                var req = this.request();
                var url = req.url().toString();
                var method = req.method();
                // Skip portal API calls, only log CDN-like requests
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("report") < 0) {
                    console.log("\n" + TAG + " ██ OkHttp " + method + " ██");
                    console.log(TAG + " " + url);
                    var h = req.headers();
                    for (var i = 0; i < h.size(); i++) console.log(TAG + "   " + h.name(i) + ": " + h.value(i));
                }
                var resp = this.execute();
                if (url.indexOf("portalCore") < 0) {
                    console.log(TAG + " -> " + resp.code());
                }
                return resp;
            };
            console.log(TAG + " OkHttp hooked");
        } catch (e) {
            console.log(TAG + " OkHttp err: " + e);
        }
    });
}

// ─── Startup ───
console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " CDN hook v2 — play VOD to capture!");
console.log(TAG + " ════════════════════════════════════");

hookRanger();
hookNative();
hookOkHttp();

console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " Hooks ready. Navigate to a VOD!");
console.log(TAG + " ════════════════════════════════════");
