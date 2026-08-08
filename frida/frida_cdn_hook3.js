/*
 * frida_cdn_hook3.js — captura CDN URLs via Java hooks
 * En vez de hookear connect/SSL_write nativos (falla en x86_64),
 * hookeamos las clases Java que manejan URLs: URL, HttpURLConnection, OkHttp
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

function hookAll() {
    Java.perform(function () {

        // ─── 1. Ranger NativeJni.Call ───
        try {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);
                if (method === "PrepareProgram" || method === "SetMedia" || method === "SetEntries" || method === "SetEnv") {
                    console.log("\n" + TAG + " ██ Ranger." + method + " ██");
                    console.log(TAG + " IN:  " + body.substring(0, 2000));
                    if (result) console.log(TAG + " OUT: " + (result.length > 500 ? result.substring(0, 500) : result));
                }
                if (method === "GetStatus") {
                    try {
                        var j = JSON.parse(result);
                        if (j.res) {
                            var s = JSON.parse(j.res);
                            if (s.play_url || s.url) {
                                console.log("\n" + TAG + " ██ ★★★ PLAY_URL ★★★ ██");
                                console.log(TAG + " " + JSON.stringify(s));
                            }
                        }
                    } catch (e) {}
                }
                return result;
            };
            console.log(TAG + " [OK] Ranger.Call");
        } catch (e) { console.log(TAG + " [X] Ranger: " + e); }

        // ─── 2. java.net.URL constructor ───
        try {
            var URL = Java.use("java.net.URL");
            URL.$init.overload("java.lang.String").implementation = function (u) {
                if (u && (u.indexOf("3ccxtimf") >= 0 || u.indexOf("hetvomaug") >= 0 || u.indexOf("swzablvpm") >= 0 ||
                    u.indexOf("pvwacsgqh") >= 0 || u.indexOf("7r03dh6rph") >= 0 || u.indexOf("vynbszicd") >= 0 ||
                    u.indexOf("rdgqkfxio") >= 0 || u.indexOf("srr3ifq00yp") >= 0 || u.indexOf("m3u8") >= 0 ||
                    u.indexOf("ewgp7ypy2") >= 0 || u.indexOf(".mp4") >= 0 || u.indexOf(".ts") >= 0)) {
                    console.log("\n" + TAG + " ██ ★★★ java.net.URL ★★★ ██");
                    console.log(TAG + " " + u);
                    console.log(TAG + " stack: " + Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
                }
                return this.$init(u);
            };
            console.log(TAG + " [OK] java.net.URL");
        } catch (e) { console.log(TAG + " [X] URL: " + e); }

        // ─── 3. HttpURLConnection.connect ───
        try {
            var HttpConn = Java.use("java.net.HttpURLConnection");
            HttpConn.connect.implementation = function () {
                var url = this.getURL().toString();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("google") < 0 &&
                    url.indexOf("firebase") < 0 && url.indexOf("umeng") < 0) {
                    console.log("\n" + TAG + " ██ HttpURLConnection ██");
                    console.log(TAG + " " + url);
                    var reqProps = this.getRequestProperties();
                    console.log(TAG + " headers: " + reqProps.toString());
                }
                return this.connect();
            };
            console.log(TAG + " [OK] HttpURLConnection");
        } catch (e) { console.log(TAG + " [X] HttpConn: " + e); }

        // ─── 4. OkHttp — hook both execute and enqueue ───
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function () {
                var req = this.request();
                var url = req.url().toString();
                var method = req.method();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("report") < 0 &&
                    url.indexOf("umeng") < 0 && url.indexOf("firebase") < 0) {
                    console.log("\n" + TAG + " ██ OkHttp." + method + " ██");
                    console.log(TAG + " " + url);
                    var h = req.headers();
                    for (var i = 0; i < h.size(); i++) console.log(TAG + "   " + h.name(i) + ": " + h.value(i));
                    var body = req.body();
                    if (body) {
                        try {
                            var Buffer = Java.use("okio.Buffer");
                            var buf = Buffer.$new();
                            body.writeTo(buf);
                            var bodyStr = buf.readUtf8();
                            if (bodyStr.length > 0) console.log(TAG + " body: " + bodyStr.substring(0, 2000));
                        } catch (e) {}
                    }
                }
                var resp = this.execute();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0) {
                    console.log(TAG + " -> " + resp.code() + " " + url.substring(0, 80));
                }
                return resp;
            };
            console.log(TAG + " [OK] OkHttp.execute");
        } catch (e) { console.log(TAG + " [X] OkHttp: " + e); }

        // ─── 5. Hook Ranger Sources entity — capture CDN URLs being constructed ───
        try {
            var Sources = Java.use("com.titans.entity.Sources");
            Sources.getMedia_code.implementation = function () {
                var mc = this.getMedia_code();
                var ma = this.getMain_addr();
                var auth = this.getAuth();
                var lic = this.getLicense();
                console.log("\n" + TAG + " ██ Sources.getMedia_code ██");
                console.log(TAG + " media_code: " + mc);
                console.log(TAG + " main_addr: " + ma);
                console.log(TAG + " auth: " + auth);
                console.log(TAG + " license: " + lic);
                return mc;
            };
            console.log(TAG + " [OK] Sources.getMedia_code");
        } catch (e) { console.log(TAG + " [X] Sources: " + e); }

        // ─── 6. Hook DownloadParams — the download feature constructs actual CDN URLs ───
        try {
            var DP = Java.use("com.download.bean.DownloadParams");
            DP.getUrl.implementation = function () {
                var u = this.getUrl();
                var mc = this.getMedia_code();
                var auth = this.getAuth();
                var lic = this.getLicense();
                console.log("\n" + TAG + " ██ ★★★ DownloadParams.getUrl ★★★ ██");
                console.log(TAG + " url: " + u);
                console.log(TAG + " media_code: " + mc);
                console.log(TAG + " auth: " + auth);
                console.log(TAG + " license: " + lic);
                return u;
            };
            console.log(TAG + " [OK] DownloadParams.getUrl");
        } catch (e) { console.log(TAG + " [X] DownloadParams: " + e); }

        // ─── 7. Hook play preparation — k3.C3973d where media_code is matched to CDN ───
        try {
            var playPrep = Java.use("k3.C3973d");
            // Look for methods that take Sources or return URLs
            var methods = playPrep.class.getDeclaredMethods();
            for (var i = 0; i < methods.length; i++) {
                console.log(TAG + " C3973d method: " + methods[i].getName() + " " + methods[i].toGenericString());
            }
        } catch (e) { console.log(TAG + " [X] C3973d enum: " + e); }

        // ─── 8. Hook DES encryption used for download params ───
        try {
            var cipher = Java.use("cc.AbstractC1235i");
            var cMethods = cipher.class.getDeclaredMethods();
            for (var i = 0; i < cMethods.length; i++) {
                var m = cMethods[i];
                console.log(TAG + " AbstractC1235i method: " + m.getName() + " → " + m.getReturnType().getName());
            }
        } catch (e) { console.log(TAG + " [X] AbstractC1235i enum: " + e); }

        // ─── 9. Hook Ranger AbstractC2309a — JSON builder for Ranger commands ───
        try {
            var builder = Java.use("com.titan.ranger.AbstractC2309a");
            var bMethods = builder.class.getDeclaredMethods();
            for (var i = 0; i < bMethods.length; i++) {
                console.log(TAG + " AbstractC2309a method: " + bMethods[i].getName());
            }
        } catch (e) { console.log(TAG + " [X] AbstractC2309a enum: " + e); }

    });
}

// ─── Start ───
console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " CDN hook v3 — Java-only, no native!");
console.log(TAG + " ════════════════════════════════════");
hookAll();
console.log(TAG + " ════════════════════════════════════");
console.log(TAG + " Navigate to VOD and PLAY an episode!");
console.log(TAG + " ════════════════════════════════════");
