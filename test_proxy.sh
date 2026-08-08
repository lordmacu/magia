#!/bin/bash
# Launch app with Frida, detect proxy port, forward it, and test access

LOG=/tmp/frida_v3.log
rm -f "$LOG"

# Launch Frida in background
frida -D emulator-5554 -f com.xuper.netxxus -l frida_cdn_hook3.js > "$LOG" 2>&1 &
FPID=$!
echo "Frida PID: $FPID"

# Wait for play_url to appear
for i in $(seq 1 30); do
    sleep 2
    PORT=$(grep -o 'mem://127.0.0.1:[0-9]*' "$LOG" | head -1 | grep -o '[0-9]*$')
    if [ -n "$PORT" ]; then
        echo "=== DETECTED PROXY PORT: $PORT ==="
        break
    fi
    echo "waiting... ($i)"
done

if [ -z "$PORT" ]; then
    echo "FAILED: no port detected"
    kill $FPID 2>/dev/null
    exit 1
fi

# Forward port
adb -s emulator-5554 forward tcp:$PORT tcp:$PORT
echo "Port forwarded: $PORT"

# Also try from INSIDE the emulator
echo ""
echo "=== Testing from inside emulator ==="
MEDIA="cyx_50fdcc0817d61_720p"

echo "--- snapinfo ---"
adb -s emulator-5554 shell "curl -s http://127.0.0.1:$PORT/vod/0/$MEDIA.snapinfo 2>/dev/null | head -5 || echo 'no curl, trying wget'"

echo "--- m3u8 ---"
adb -s emulator-5554 shell "curl -s http://127.0.0.1:$PORT/vod/0/$MEDIA.m3u8 2>/dev/null | head -20 || echo 'no curl'"

echo ""
echo "=== Testing from Mac via port forward ==="

echo "--- snapinfo ---"
curl -s --connect-timeout 3 "http://127.0.0.1:$PORT/vod/0/$MEDIA.snapinfo" 2>&1 | head -5

echo "--- m3u8 ---"
curl -s --connect-timeout 3 "http://127.0.0.1:$PORT/vod/0/$MEDIA.m3u8" 2>&1 | head -20

echo ""
echo "=== Testing other URL patterns ==="
curl -s --connect-timeout 3 -o /dev/null -w "GET / -> %{http_code}\n" "http://127.0.0.1:$PORT/" 2>&1
curl -s --connect-timeout 3 -o /dev/null -w "GET /status -> %{http_code}\n" "http://127.0.0.1:$PORT/status" 2>&1
curl -s --connect-timeout 3 -o /dev/null -w "GET /vod/ -> %{http_code}\n" "http://127.0.0.1:$PORT/vod/" 2>&1

# Keep Frida alive for a bit more
sleep 5
kill $FPID 2>/dev/null
wait $FPID 2>/dev/null
echo "Done"
