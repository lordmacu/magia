/*
 * frida_rpc_agent.js — Robust RPC agent for VOD resolution via Ranger
 *
 * Protocol:
 *   Python → Frida:  {type: "resolve", media, license, format, vcodec}
 *   Frida → Python:  {type: "resolved", ok, media, snapinfo_url, play_url, port, ...}
 *   Frida → Python:  {type: "ready"}
 *   Frida → Python:  {type: "proxy_port", port}
 */

var TAG = "[RPC]";
var proxyPort = 0;
var hooksInstalled = false;

// ─── Anti-Frida bypass ───
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

// ─── Install hooks with retry (Java VM may not be ready yet) ───
function installHooks() {
    if (hooksInstalled) return;
    try {
        Java.perform(function () {
            var NativeJni = Java.use("com.titan.ranger.NativeJni");
            NativeJni.Call.implementation = function (method, body) {
                var result = this.Call(method, body);

                if (method === "OnPlayerOperation") {
                    try {
                        var j = JSON.parse(body);
                        if (j.operation === "setDataSource" && j.data) {
                            var m = j.data.match(/:(\d+)/);
                            if (m) {
                                proxyPort = parseInt(m[1]);
                                send({type: "proxy_port", port: proxyPort});
                            }
                        }
                    } catch (e) {}
                }

                return result;
            };
            hooksInstalled = true;
            console.log(TAG + " Ranger hooked");
            send({type: "ready"});
        });
    } catch (e) {
        console.log(TAG + " Hook attempt failed (Java not ready): " + e);
    }
}

// Try immediately, then retry with delay
installHooks();
if (!hooksInstalled) {
    console.log(TAG + " Retrying hooks in 3s...");
    setTimeout(function () {
        installHooks();
        if (!hooksInstalled) {
            console.log(TAG + " Retrying hooks in 5s...");
            setTimeout(function () {
                installHooks();
                if (!hooksInstalled) {
                    console.log(TAG + " Retrying hooks in 8s...");
                    setTimeout(function () {
                        installHooks();
                        if (!hooksInstalled) {
                            send({type: "ready"}); // signal ready anyway so Python doesn't hang
                            console.log(TAG + " WARNING: hooks not installed, will try on first resolve");
                        }
                    }, 8000);
                }
            }, 5000);
        }
    }, 3000);
}

// ─── Resolve handler ───
function handleResolve(msg) {
    if (!hooksInstalled) installHooks();

    var media = msg.media;
    var license = msg.license;
    var format = msg.format || "mp4";
    var vcodec = msg.vcodec || "h264";

    Java.perform(function () {
        Java.choose("com.titan.ranger.NativeJni", {
            onMatch: function (instance) {
                var program = JSON.stringify({
                    buss: "vod",
                    cause: "user",
                    episode: "1",
                    from: "detail",
                    media: media,
                    medias: [{
                        format: format,
                        lang: "",
                        license: license,
                        name: media,
                        quality: "480p",
                        vcodec: vcodec
                    }],
                    name: media,
                    start: 0,
                    title: "download"
                });

                var body = JSON.stringify({
                    instance: 0,
                    name: media,
                    program: program,
                    extra: "vod"
                });

                try {
                    var prepResult = instance.Call("PrepareProgram", body);
                    console.log(TAG + " PrepareProgram OK for " + media.substring(0, 8));
                } catch (e) {
                    send({type: "resolved", ok: false, media: media, error: "PrepareProgram: " + e});
                    return;
                }

                var attempts = 0;
                var maxAttempts = 40;
                var pollId = setInterval(function () {
                    attempts++;
                    if (attempts > maxAttempts) {
                        clearInterval(pollId);
                        send({type: "resolved", ok: false, media: media, error: "timeout"});
                        return;
                    }

                    Java.perform(function () {
                        Java.choose("com.titan.ranger.NativeJni", {
                            onMatch: function (inst) {
                                try {
                                    var statusBody = JSON.stringify({instance: 0, name: media});
                                    var status = inst.Call("GetStatus", statusBody);
                                    var j = JSON.parse(status);
                                    if (j.res) {
                                        var s = JSON.parse(j.res);
                                        if (s.snapinfo_url && s.snapinfo_url !== "" && s.media === media) {
                                            clearInterval(pollId);
                                            send({
                                                type: "resolved",
                                                ok: true,
                                                media: media,
                                                play_url: s.play_url || "",
                                                snapinfo_url: s.snapinfo_url,
                                                format: s.format || "",
                                                port: proxyPort
                                            });
                                        }
                                    }
                                } catch (e) {}
                            },
                            onComplete: function () {}
                        });
                    });
                }, 500);
            },
            onComplete: function () {}
        });
    });
}

// ─── Message loop ───
function waitForMessage() {
    recv("resolve", function (msg) {
        console.log(TAG + " Resolve: " + msg.media.substring(0, 8) + "...");
        handleResolve(msg);
        waitForMessage();
    });
}
waitForMessage();

rpc.exports = {
    ping: function () { return hooksInstalled ? "pong" : "not_ready"; }
};

console.log(TAG + " Agent loaded");
