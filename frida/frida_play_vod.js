/*
 * frida_play_vod.js — Force VOD playback via Ranger and capture CDN traffic
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

function hookAndPlay() {
    Java.perform(function () {
        // Hook Ranger to capture everything
        try {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);

                // Log ALL methods to see what Ranger does for VOD
                if (method !== "GetStatus") {
                    console.log("\n" + TAG + " ██ Ranger." + method + " ██");
                    console.log(TAG + " IN:  " + body.substring(0, 3000));
                    if (result) console.log(TAG + " OUT: " + (result.length > 500 ? result.substring(0, 500) : result));
                }

                // Catch play_url
                if (method === "GetStatus") {
                    try {
                        var j = JSON.parse(result);
                        if (j.res) {
                            var s = JSON.parse(j.res);
                            if (s.play_url) {
                                console.log("\n" + TAG + " ★★★ PLAY_URL: " + s.play_url + " ★★★");
                                console.log(TAG + " media: " + s.media);
                                console.log(TAG + " format: " + s.format);
                                console.log(TAG + " host: " + s.host);
                                console.log(TAG + " links: " + JSON.stringify(s.links));
                                console.log(TAG + " buffer: " + s.buffer);
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

        // Hook java.net.URL for CDN URLs
        try {
            var URL = Java.use("java.net.URL");
            URL.$init.overload("java.lang.String").implementation = function (u) {
                if (u && (u.indexOf("3ccxtimf") >= 0 || u.indexOf("hetvomaug") >= 0 || u.indexOf("swzablvpm") >= 0 ||
                    u.indexOf("pvwacsgqh") >= 0 || u.indexOf("m3u8") >= 0 || u.indexOf("ewgp7ypy2") >= 0 ||
                    u.indexOf(".mp4") >= 0 || u.indexOf(".ts") >= 0 || u.indexOf("vod/") >= 0)) {
                    console.log("\n" + TAG + " ★★★ URL: " + u + " ★★★");
                }
                return this.$init(u);
            };
        } catch (e) {}

        // Hook OkHttp
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function () {
                var req = this.request();
                var url = req.url().toString();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("report") < 0 &&
                    url.indexOf("umeng") < 0 && url.indexOf("firebase") < 0 && url.indexOf("notice") < 0 &&
                    url.indexOf("MarketServer") < 0) {
                    console.log("\n" + TAG + " ██ OkHttp " + req.method() + " ██");
                    console.log(TAG + " " + url);
                    var h = req.headers();
                    for (var i = 0; i < h.size(); i++) console.log(TAG + "   " + h.name(i) + ": " + h.value(i));
                }
                var resp = this.execute();
                if (url.indexOf("portalCore") < 0 && url.indexOf("adserver") < 0 && url.indexOf("notice") < 0 &&
                    url.indexOf("MarketServer") < 0) {
                    console.log(TAG + " -> " + resp.code() + " " + url.substring(0, 80));
                }
                return resp;
            };
        } catch (e) {}

        console.log(TAG + " All hooks ready");

        // Wait for app to fully initialize, then inject VOD play
        setTimeout(function () {
            Java.perform(function () {
                console.log("\n" + TAG + " ═══════════════════════════════════");
                console.log(TAG + " INJECTING VOD PrepareProgram...");
                console.log(TAG + " ═══════════════════════════════════");

                try {
                    var NativeJni = Java.use("com.titan.ranger.NativeJni");

                    // Dragon Ball ep1 h264/mp4 media_code
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

                    console.log(TAG + " Calling PrepareProgram with VOD data...");
                    var result = NativeJni.Call("PrepareProgram", body);
                    console.log(TAG + " PrepareProgram result: " + result);

                    // Poll GetStatus a few times
                    for (var i = 0; i < 15; i++) {
                        (function(idx) {
                            setTimeout(function () {
                                Java.perform(function () {
                                    try {
                                        var statusBody = JSON.stringify({ instance: 0, name: media });
                                        var status = NativeJni.Call("GetStatus", statusBody);
                                        var j = JSON.parse(status);
                                        if (j.res) {
                                            var s = JSON.parse(j.res);
                                            if (s.play_url && s.play_url !== "") {
                                                console.log("\n" + TAG + " ★★★ VOD READY ★★★");
                                                console.log(TAG + " play_url: " + s.play_url);
                                                console.log(TAG + " format: " + s.format);
                                                console.log(TAG + " host: " + s.host);
                                                console.log(TAG + " links: " + JSON.stringify(s.links));
                                                console.log(TAG + " full: " + JSON.stringify(s));
                                            } else {
                                                console.log(TAG + " status[" + idx + "]: buffering... " + (s.buffer || 0));
                                            }
                                        }
                                    } catch (e) {
                                        console.log(TAG + " status err: " + e);
                                    }
                                });
                            }, (idx + 1) * 2000);
                        })(i);
                    }
                } catch (e) {
                    console.log(TAG + " PrepareProgram err: " + e);
                }
            });
        }, 10000);  // Wait 10s for app init
    });
}

console.log(TAG + " ═══════════════════════════════════");
console.log(TAG + " VOD injector — will play in 10s...");
console.log(TAG + " ═══════════════════════════════════");
hookAndPlay();
