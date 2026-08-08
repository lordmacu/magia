/*
 * frida_vod_capture.js — Capture complete VOD flow: SLB + CDN
 * Hooks NativeJni.Call + all network layers + auto-injects VOD
 */

var TAG = "[VOD]";

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

function hookAll() {
    Java.perform(function () {

        // ─── 1. Ranger NativeJni.Call — log EVERYTHING ───
        try {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);

                // Log ALL calls except noisy GetStatus polling
                if (method !== "GetStatus") {
                    console.log("\n" + TAG + " ██ Ranger." + method + " ██");
                    console.log(TAG + " IN:  " + body.substring(0, 5000));
                    if (result) console.log(TAG + " OUT: " + (result.length > 3000 ? result.substring(0, 3000) + "..." : result));
                }

                // Watch GetStatus for play_url
                if (method === "GetStatus") {
                    try {
                        var j = JSON.parse(result);
                        if (j.res) {
                            var s = JSON.parse(j.res);
                            if (s.play_url && s.play_url !== "") {
                                console.log("\n" + TAG + " ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★");
                                console.log(TAG + " ★ PLAY_URL: " + s.play_url);
                                console.log(TAG + " ★ host: " + s.host);
                                console.log(TAG + " ★ format: " + s.format);
                                console.log(TAG + " ★ links: " + JSON.stringify(s.links));
                                console.log(TAG + " ★ buffer: " + s.buffer);
                                console.log(TAG + " ★ FULL: " + JSON.stringify(s));
                                console.log(TAG + " ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★");
                            }
                        }
                    } catch (e) {}
                }

                return result;
            };
            console.log(TAG + " [OK] Ranger.Call hooked");
        } catch (e) { console.log(TAG + " [X] Ranger: " + e); }

        // ─── 2. java.net.URL ───
        try {
            var URL = Java.use("java.net.URL");
            URL.$init.overload("java.lang.String").implementation = function (u) {
                if (u && (u.indexOf("vfltbr") >= 0 || u.indexOf("3ccxtimf") >= 0 || u.indexOf("hetvomaug") >= 0 ||
                    u.indexOf("swzablvpm") >= 0 || u.indexOf("pvwacsgqh") >= 0 || u.indexOf("vynbszicd") >= 0 ||
                    u.indexOf("rdgqkfxio") >= 0 || u.indexOf("m3u8") >= 0 || u.indexOf(".mp4") >= 0 ||
                    u.indexOf(".ts") >= 0 || u.indexOf(":18084") >= 0 || u.indexOf("slb") >= 0 ||
                    u.indexOf("vod/") >= 0)) {
                    console.log("\n" + TAG + " ★ URL: " + u);
                }
                return this.$init(u);
            };
            console.log(TAG + " [OK] URL hooked");
        } catch (e) { console.log(TAG + " [X] URL: " + e); }

        // ─── 3. OkHttp ───
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function () {
                var req = this.request();
                var url = req.url().toString();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("report") < 0 &&
                    url.indexOf("umeng") < 0 && url.indexOf("firebase") < 0 && url.indexOf("notice") < 0 &&
                    url.indexOf("MarketServer") < 0 && url.indexOf("google") < 0) {
                    console.log("\n" + TAG + " ██ OkHttp " + req.method() + " ██");
                    console.log(TAG + " URL: " + url);
                    var h = req.headers();
                    for (var i = 0; i < h.size(); i++) console.log(TAG + "   " + h.name(i) + ": " + h.value(i));
                }
                var resp = this.execute();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("notice") < 0 &&
                    url.indexOf("MarketServer") < 0 && url.indexOf("google") < 0) {
                    console.log(TAG + " -> " + resp.code() + " " + url.substring(0, 100));
                }
                return resp;
            };
            console.log(TAG + " [OK] OkHttp hooked");
        } catch (e) { console.log(TAG + " [X] OkHttp: " + e); }

        // ─── 4. Sources entity ───
        try {
            var Sources = Java.use("com.titans.entity.Sources");
            Sources.getMedia_code.implementation = function () {
                var mc = this.getMedia_code();
                var ma = this.getMain_addr();
                var auth = this.getAuth();
                var lic = this.getLicense();
                console.log("\n" + TAG + " ██ Sources ██");
                console.log(TAG + " media_code: " + mc);
                console.log(TAG + " main_addr: " + ma);
                console.log(TAG + " auth: " + auth);
                console.log(TAG + " license: " + lic);
                return mc;
            };
            console.log(TAG + " [OK] Sources hooked");
        } catch (e) { console.log(TAG + " [X] Sources: " + e); }

        // ─── 5. DownloadParams ───
        try {
            var DP = Java.use("com.download.bean.DownloadParams");
            DP.getUrl.implementation = function () {
                var u = this.getUrl();
                console.log("\n" + TAG + " ★★★ DownloadParams.url: " + u);
                console.log(TAG + " media_code: " + this.getMedia_code());
                console.log(TAG + " auth: " + this.getAuth());
                console.log(TAG + " license: " + this.getLicense());
                return u;
            };
            console.log(TAG + " [OK] DownloadParams hooked");
        } catch (e) { console.log(TAG + " [X] DownloadParams: " + e); }

        // ─── 6. Hook Socket connect to see SLB connections ───
        try {
            var Socket = Java.use("java.net.Socket");
            Socket.connect.overload("java.net.SocketAddress", "int").implementation = function (addr, timeout) {
                var s = addr.toString();
                if (s.indexOf("18084") >= 0 || s.indexOf("vfltbr") >= 0) {
                    console.log("\n" + TAG + " ★★★ Socket.connect: " + s + " timeout=" + timeout);
                    console.log(TAG + " stack: " + Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
                }
                return this.connect(addr, timeout);
            };
            console.log(TAG + " [OK] Socket.connect hooked");
        } catch (e) { console.log(TAG + " [X] Socket: " + e); }

        // ─── 7. Hook OutputStream.write to capture SLB protocol data ───
        try {
            var BOS = Java.use("java.io.BufferedOutputStream");
            BOS.write.overload("[B", "int", "int").implementation = function (buf, off, len) {
                try {
                    var bytes = Java.array('byte', buf);
                    if (len > 10 && len < 10000) {
                        var str = "";
                        for (var i = off; i < off + Math.min(len, 200); i++) {
                            var b = bytes[i] & 0xFF;
                            if (b >= 32 && b < 127) str += String.fromCharCode(b);
                            else str += ".";
                        }
                        if (str.indexOf("media") >= 0 || str.indexOf("slb") >= 0 || str.indexOf("vod") >= 0 ||
                            str.indexOf("auth") >= 0 || str.indexOf("content") >= 0 || str.indexOf("GET") >= 0 ||
                            str.indexOf("POST") >= 0) {
                            console.log("\n" + TAG + " ██ BufferedOutputStream.write " + len + "b ██");
                            console.log(TAG + " " + str);
                            // hex dump first 100 bytes
                            var hex = "";
                            for (var i = off; i < off + Math.min(len, 100); i++) {
                                var h = (bytes[i] & 0xFF).toString(16);
                                hex += (h.length < 2 ? "0" : "") + h + " ";
                            }
                            console.log(TAG + " HEX: " + hex);
                        }
                    }
                } catch (e) {}
                return this.write(buf, off, len);
            };
            console.log(TAG + " [OK] BufferedOutputStream hooked");
        } catch (e) { console.log(TAG + " [X] BOS: " + e); }

        console.log(TAG + " All hooks ready!");
    });
}

function injectVOD() {
    Java.perform(function () {
        console.log("\n" + TAG + " ═══════════════════════════════════");
        console.log(TAG + " INJECTING VOD via Java.choose...");
        console.log(TAG + " ═══════════════════════════════════");

        Java.choose("com.titan.ranger.NativeJni", {
            onMatch: function (instance) {
                console.log(TAG + " Found NativeJni instance: " + instance);

                // Dragon Ball ep1 h264/mp4
                var media = "3966FDF91AD740ADA45DC23D828542A4";
                var license = "app_id=com.android.msandroid&tag=free&scheme=md5-01&media_code=" + media + "&expired=1786249379&token=469E5BA22649810A8DCE0F55ABED764E";

                var program = JSON.stringify({
                    buss: "vod",
                    cause: "user",
                    episode: "1",
                    from: "detail",
                    media: media,
                    medias: [{
                        format: "mp4",
                        lang: "",
                        license: license,
                        name: media,
                        quality: "480p",
                        vcodec: "h264"
                    }],
                    name: media,
                    start: 0,
                    title: "Dragon Ball 001"
                });

                var body = JSON.stringify({
                    instance: 0,
                    name: media,
                    program: program,
                    extra: "vod"
                });

                console.log(TAG + " Calling PrepareProgram...");
                try {
                    var result = instance.Call("PrepareProgram", body);
                    console.log(TAG + " PrepareProgram result: " + result);
                } catch (e) {
                    console.log(TAG + " PrepareProgram err: " + e);
                }
            },
            onComplete: function () {
                console.log(TAG + " Java.choose complete");
            }
        });

        // Also poll GetStatus
        var pollCount = 0;
        var pollId = setInterval(function () {
            pollCount++;
            if (pollCount > 30) {
                clearInterval(pollId);
                return;
            }
            Java.perform(function () {
                Java.choose("com.titan.ranger.NativeJni", {
                    onMatch: function (instance) {
                        try {
                            var media = "3966FDF91AD740ADA45DC23D828542A4";
                            var statusBody = JSON.stringify({ instance: 0, name: media });
                            var status = instance.Call("GetStatus", statusBody);
                            var j = JSON.parse(status);
                            if (j.res) {
                                var s = JSON.parse(j.res);
                                if (s.play_url && s.play_url !== "") {
                                    console.log("\n" + TAG + " ★★★ VOD PLAY_URL FOUND ★★★");
                                    console.log(TAG + " " + JSON.stringify(s));
                                    clearInterval(pollId);
                                } else {
                                    console.log(TAG + " poll[" + pollCount + "]: buffering " + (s.buffer || 0) + "% state=" + (s.state || "?"));
                                }
                            }
                        } catch (e) {}
                    },
                    onComplete: function () {}
                });
            });
        }, 2000);
    });
}

// ─── Start ───
console.log(TAG + " ═══════════════════════════════════");
console.log(TAG + " VOD capture — hooks + auto-inject");
console.log(TAG + " ═══════════════════════════════════");
hookAll();

// Wait 12s for app to fully load, then inject VOD
setTimeout(function () {
    injectVOD();
}, 12000);
