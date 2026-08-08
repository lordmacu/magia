# Magia

> Search, browse, download movies & series, and get live TV streaming URLs — all from your terminal.

## Disclaimer

**This project does not own, operate, host, or distribute any content or servers.** All content accessed through this tool belongs to and is served by the third-party IPTV platform **Magis TV / Xuper** (`com.xuper.netxxus`). This project is purely the result of reverse engineering the Magis TV Android APK for personal educational and research purposes. No media files, streams, or server infrastructure are provided, hosted, or redistributed by this project or its author. Use at your own risk and responsibility.

---

```
  ███╗   ███╗ █████╗  ██████╗ ██╗ █████╗
  ████╗ ████║██╔══██╗██╔════╝ ██║██╔══██╗
  ██╔████╔██║███████║██║  ███╗██║███████║
  ██║╚██╔╝██║██╔══██║██║   ██║██║██╔══██║
  ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║██║  ██║
  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═╝
```

Magia is an interactive CLI tool that connects to an IPTV portal and lets you:

- **Search** for any movie or series by name
- **Browse** the catalog by genre, year, country, or actor
- **Download** movies and full series (auto-organized in folders)
- **View details** — cast, score, description — before deciding to download
- **Get recommendations** — "liked this? try that"
- **Access 1,000+ live TV channels** with stream credentials

No Android emulator required. No Frida. Pure Python.

---

## Quick Install

```bash
curl -sL https://raw.githubusercontent.com/lordmacu/magia/main/install.sh | bash
```

Or manually:

```bash
git clone https://github.com/lordmacu/magia.git
cd magia
pip install pycryptodome requests
cp .env.example .env
# Edit .env with your values (see Configuration below)
python3 magia.py
```

## Requirements

- Python 3.8+
- `pycryptodome` — for 3DES encryption
- `requests` — HTTP client

---

## Configuration

All secrets and settings live in `.env` (never hardcoded). Copy the example and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `IPTV_3DES_KEY` | Yes | 3DES encryption key (48 hex chars) — from APK analysis |
| `IPTV_HOSTS` | Yes | API host(s), comma-separated (primary,fallback) |
| `IPTV_APP_ID` | Yes | APK package identifier |
| `IPTV_DEVICE_SN` | Yes | Device serial number (fingerprint) |
| `IPTV_APK_VERSION` | No | APK internal version code (server accepts empty) |
| `IPTV_DEVICE_DRM_ID` | No | DRM device identifier (server accepts empty) |
| `IPTV_DEVICE_TOKEN` | No | Firebase/push device token (server accepts empty) |
| `IPTV_DEVICE_RESERVE1` | No | Reserved device field (server accepts empty) |
| `IPTV_USERNAME` | No | Account email (for premium tier) |
| `IPTV_PASSWORD` | No | Encrypted password (for premium tier) |
| `IPTV_DOWNLOAD_DIR` | No | Download folder name (default: `downloads`) |

Without a `.env` file, the app will not start — this is by design to prevent leaking secrets into source control.

---

## Usage

### Starting Magia

```bash
python3 magia.py
# or if you ran the installer:
magia
```

You'll see the banner and be asked to choose an authentication method:

```
  ┌────────────────────────────────────────────────┐
  │ Authentication                                 │
  └────────────────────────────────────────────────┘

    1  Free tier (no login)   auto-activates, access to free content
    2  Login with account     email + password for premium content
```

### Searching

Pick option **1** from the main menu and type your query:

```
  > Search: dragon ball

  Results (3 of 15):
    1  [SERIE] Dragon Ball                    1986 | ★8.6 | Animation,Action
    2  [PELI]  Dragon Ball Super: Broly       2018 | ★7.9 | Animation
    3  [PELI]  Dragon Ball Super: Super Hero  2022 | ★7.3 | Animation
```

### Movies

When you select a movie, you choose between:

```
    1  Download       download the movie file
    2  View details   full info (cast, description, streams)
```

**View details** shows everything before you commit to downloading:

```
  Year:      2018
  Score:     7.9
  Genre:     Animation,Action,Adventure
  Country:   Japan
  Director:  Tatsuya Nagamine
  Cast:      Masako Nozawa, Ryou Horikawa, Bin Shimada...

  A planet destroyed, a powerful race reduced to nothing...
```

Then asks if you want to download.

### Series

Series episodes auto-organize into their own folder:

```
downloads/
  Dragon_Ball/
    ep001.mp4
    ep002.mp4
    ep003.mp4
    ...
```

You can download all episodes, a range (e.g., 1-10), or a single episode.

### Live TV

Browse 1,000+ channels across 30+ categories. Since live streams need SLB resolution, Magia shows you the stream credentials to use with your favorite player:

```
  Channel:     ESPN Deportes HD
  Play Code:   espn_deportes_hd
  Format:      ts
  License:     app_id=...&tag=free&scheme=md5-01&...
```

### Browse Options

| Menu | What it does |
|------|-------------|
| **Search** | Search by name |
| **Latest** | Browse newest content (sorted by release date) |
| **By Genre** | Action, Comedy, Horror, Anime, Sci-Fi, etc. |
| **By Year** | Filter by release year |
| **By Country** | Japan, South Korea, USA, Mexico, etc. |
| **By Actor** | Find content by actor or director name |
| **Recommendations** | Pick something you like, get similar titles |
| **Live TV** | 1,000+ channels by category |

### Keyboard Shortcuts

- Type a number to select an option
- `0` goes back
- `Ctrl+C` exits

---

## File Structure

```
magia/
├── magia.py              Main interactive CLI
├── iptv_client.py        IPTV portal API client
├── download_iptv.py      Standalone batch downloader (Dragon Ball)
├── install.sh            One-line installer script
├── .env                  Your secrets (git-ignored)
├── .env.example          Template for .env
├── .gitignore            Keeps secrets and downloads out of git
└── downloads/            Where your media goes
    └── Dragon_Ball/
        ├── ep001.mp4
        └── ...
```

---

---

# For Nerds

> Technical deep-dive into how Magia works — protocol reverse-engineering, cryptography, CDN architecture, and the full request/response pipeline.

## How It Was Built

Magia was reverse-engineered from a commercial IPTV Android app (`com.xuper.netxxus`, branded as "Xuper Hydra"). The process involved:

1. **Static analysis** — APK decompilation with jadx and apktool
2. **Dynamic analysis** — Frida instrumentation on a rooted Android emulator
3. **Protocol reconstruction** — Pure Python reimplementation of the encrypted API protocol
4. **CDN reverse-engineering** — Cloudflare CDN auth flow for direct HTTP downloads

No running Android device or emulator is needed to use Magia — the entire protocol runs in pure Python.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         MAGIA CLI                               │
│  magia.py — Interactive menus, search, browse, download         │
└────────────┬──────────────────────────────────┬─────────────────┘
             │                                  │
             ▼                                  ▼
┌─────────────────────┐            ┌────────────────────────────┐
│   iptv_client.py    │            │     Direct HTTP Download   │
│   Portal API Client │            │   GET /vod/{id}_media.mp4  │
│                     │            │   Headers:                 │
│  encrypt(json)      │            │     Content-Auth: <cf_tok> │
│  POST /portalCore/* │            │     Content-License: <lic> │
│  decrypt(response)  │            │                            │
└────────┬────────────┘            └──────────┬─────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────────┐            ┌────────────────────────────┐
│   IPTV Portal API   │            │   Cloudflare CDN           │
│   (osuhk.m3x8o50te  │            │   (yuwc.swzablvpm.com)     │
│    .com)             │            │   sign_type=cfl            │
│                     │            │                            │
│  activate / login    │            │  Serves .mp4 / .ts files   │
│  search / detail     │            │  with auth token           │
│  play_vod / get_slb  │            │                            │
│  live_data / etc     │            │                            │
└─────────────────────┘            └────────────────────────────┘
```

---

## The Encryption Protocol

Every request and response is encrypted with **3DES-ECB** (Triple DES in Electronic Codebook mode). The encoding pipeline:

```
                    ENCODING (request body)
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│   JSON   │───▶│  3DES    │───▶│  Base64  │───▶│   Hex    │
│ plaintext│    │ ECB/PKCS5│    │  encode  │    │  encode  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                     │
                                              wire format
                                              (POST body)
                                                     │
                    DECODING (response .data)         ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│   JSON   │◀───│  3DES    │◀───│  Base64  │◀───│   Hex    │
│ plaintext│    │ ECB/PKCS5│    │  decode  │    │  decode  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

The 3DES key is a 24-byte (192-bit) key stored in the `.env` file. It was extracted from the APK's native code via Frida instrumentation of the `DES3.new()` call path.

**In code (simplified):**

```python
from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad, unpad

def encrypt(json_str):
    ct = DES3.new(KEY, DES3.MODE_ECB).encrypt(pad(json_str.encode(), 8))
    return base64.b64encode(ct).decode().encode().hex()

def decrypt(wire):
    ct = base64.b64decode(bytes.fromhex(wire).decode())
    return unpad(DES3.new(KEY, DES3.MODE_ECB).decrypt(ct), 8).decode()
```

---

## VOD Download Flow

Downloading a movie or episode requires three API calls followed by a direct HTTP download:

```
Step 1: activate()              Step 2: get_slb()
┌───────────────────┐           ┌───────────────────┐
│ POST v8/active    │           │ POST getSlbInfo    │
│                   │           │                   │
│ IN:  device SN,   │           │ OUT: cdn_list[] → │
│      DRM ID       │           │   tag: "vod"      │
│                   │           │   main_addr: CDN   │
│ OUT: userToken,   │           │   url: CF auth tok │
│      userId       │           │   sign_type: cfl   │
└───────┬───────────┘           └───────┬───────────┘
        │                               │
        ▼                               ▼
Step 3: play_vod()              Step 4: HTTP GET
┌───────────────────┐           ┌───────────────────┐
│ POST startPlayVOD │           │ GET /vod/{media}   │
│                   │           │     _media.mp4     │
│ IN:  contentId    │           │                   │
│                   │           │ Headers:           │
│ OUT: episodeList  │           │  Content-Auth:     │
│  └─ movieList     │           │    <cf_auth_token> │
│     └─ contentId  │           │  Content-License:  │
│        (media_code)│          │    <vod_license>   │
│     └─ license    │           │                   │
│     └─ videoFormat│           │ → 200 OK          │
│        (mp4/ts)   │           │   binary stream   │
└───────────────────┘           └───────────────────┘
```

**Key insight:** The CDN auth token from `get_slb()` and the license from `play_vod()` are interchangeable across sessions. This means:
- Tokens from one session work in another
- Auth tokens have a ~48-hour lifetime
- The token refreshes automatically every 30 episodes

---

## Content Discovery

The portal API has multiple endpoints for content, but in practice **only `search()` works reliably** for browsing:

| Endpoint | Works? | Notes |
|----------|--------|-------|
| `search(query, page, size)` | Yes | 44,054 items, paginated, sorted by releaseTime desc |
| `filterGenre()` | Yes | Returns genre/year/country catalogs (metadata only) |
| `v4/getItemData` | Yes | Full item details |
| `similar(contentId)` | Yes | Recommendations |
| `searchResourceOrPerson` | Partial | Returns results, but `items_by_person` returns 0 |
| `getShelveData` | No | Returns empty for VOD columns |
| `getColumnContents` | No | Returns empty for type=3 columns |
| `filterByContent` | No | Returns error |

**Browse trick:** Searching for `"s"` (a single letter) returns the full catalog sorted by newest first — this is how "Latest" browsing works.

---

## Live TV Architecture

Live channels are organized in categories and accessed via a different flow:

```
live_categories()          live_data(column_id)        play_live(channel_code)
┌────────────────┐         ┌────────────────┐          ┌────────────────────┐
│ GET liveColumn │ ──────▶ │ GET liveData   │ ───────▶ │ POST startPlayLive │
│                │         │                │          │                    │
│ Returns:       │         │ Returns:       │          │ Returns:           │
│  30+ categories│         │  channels[]    │          │  liveAddressList[] │
│  (Sports, News,│         │  with codes    │          │    playCode        │
│   Movies, etc.)│         │                │          │    license         │
└────────────────┘         └────────────────┘          │    cdnType         │
                                                       │    AVFormat        │
                                                       └────────────────────┘
```

**Important:** Live streams require SLB (Server Load Balancer) resolution that involves a proprietary binary protocol. Unlike VOD content (which works via Cloudflare CDN), live streams can't be directly downloaded with simple HTTP requests. Magia shows you the stream credentials so you can use them with a compatible player.

---

## Device Fingerprinting

Every API request includes a device fingerprint injected by the app's network interceptor (class `C6357b` in the decompiled source). These fields are required — without them, the API returns auth errors:

```json
{
  "loginType": "2",
  "appLanguage": "en",
  "apkVersion": "49902",
  "appId": "com.android.msandroid",
  "hardwareInfo": "ranchu",
  "model": "sdk_gphone64_arm64",
  "sn": "<device serial from .env>",
  "drmId": "<DRM ID from .env>",
  "deviceToken": "<Firebase token from .env>",
  "reserve1": "<encoded field from .env>"
}
```

These values were captured from a running emulator instance. The `sn` (serial number) is the primary device identifier — the server uses it to track activations.

---

## Format Handling

Content is available in two format combinations:

| Video Format | Container | Codec | Priority |
|-------------|-----------|-------|----------|
| `mp4` | `.mp4` | H.264 | Preferred |
| `ts` | `.ts` | H.265/HEVC | Fallback |

Magia always tries H.264/MP4 first (smaller files, universal compatibility) and falls back to H.265/TS when H.264 isn't available.

---

## Rate Limiting

The portal API enforces rate limits. Magia respects them:

| Operation | Delay |
|-----------|-------|
| API calls (search, detail, play_vod) | 1.5 seconds |
| Between downloads | 0.5 seconds |
| CDN auth refresh | Every 30 episodes |
| Session re-activation | On 401/token expiry |

---

## Reverse Engineering Methodology

### Phase 1: Static Analysis (jadx + apktool)

The APK was decompiled to Java source. Key discoveries:

- **Entry point:** `com.xuper.netxxus` → routes through ARouter to portal activities
- **Network layer:** OkHttp interceptor `C6357b` adds device fields to every request
- **Crypto:** `DES3.new()` with ECB mode, PKCS5 padding, key from native `.so`
- **Protocol:** All payloads go through `hex(base64(3DES(json)))` transformation
- **Headers:** `apk`, `apkVer`, `spkgVer` are mandatory (missing → "version stopped" error)

### Phase 2: Dynamic Analysis (Frida)

Frida scripts (included in the repo for reference) were used to:

1. **Hook `NativeJni.Call()`** — intercepted all Ranger player operations
2. **Hook `java.net.URL`** — captured CDN URLs and auth patterns
3. **Hook OkHttp** — logged all non-analytics HTTP traffic
4. **Hook `Sources` entity** — captured media_code, auth, license in real-time
5. **Anti-Frida bypass** — patched `strstr()` and `openat()` to hide Frida's presence

### Phase 3: Protocol Reimplementation

With the crypto key and protocol structure understood, the entire flow was reimplemented in pure Python (~400 lines). The Frida scripts are no longer needed for operation — they're included for documentation.

### Key Files from RE Process

| File | Purpose |
|------|---------|
| `frida_vod_capture.js` | Full VOD flow capture (SLB + CDN hooks) |
| `frida_rpc_agent.js` | RPC agent for VOD resolution via Ranger |
| `frida_play_vod.js` | Standalone VOD playback injection |
| `frida_cdn_hook*.js` | CDN URL and auth capture variants |
| `test_proxy.sh` | Local proxy testing script |

---

## API Endpoint Reference

All endpoints are POST to `https://{host}/api/portalCore/{route}`:

| Route | Description | Key Parameters |
|-------|-------------|----------------|
| `v8/active` | Device activation (free tier) | `snToken`, `macAddr`, `reserve1` |
| `v3/loginByAccount` | Account login | `userName`, `password`, `accountType` |
| `v10/startPlayVOD` | Get VOD stream info | `contentId`, `seriesContentId` |
| `v4/startPlayLive` | Get live stream info | `channelCode`, `columnId` |
| `getSlbInfo` | Get CDN/SLB servers | (device fields only) |
| `v4/getItemData` | Content details | `contentId`, `type` |
| `search` | Search catalog | `query`, `pageSize`, `pageNum` |
| `filterGenre` | Get filter options | (device fields only) |
| `getSimilarContentByContentId` | Recommendations | `contentId` |
| `searchResourceOrPerson` | Search people | `query` |
| `liveColumn` | Live TV categories | (device fields only) |
| `liveData` | Channels in category | `columnId`, `pageSize` |

---

## Security Notes

- All secrets are stored in `.env` (git-ignored)
- No credentials are hardcoded in source code
- The 3DES key, device fingerprint, and API hosts are all externalized
- SSL verification is disabled (`verify=False`) because the portal uses a custom certificate chain
- CDN auth tokens expire in ~48 hours and auto-refresh

---

## Disclaimer

**This project does not own, operate, host, or distribute any content or servers.** All content accessed through this tool belongs to and is served by the third-party IPTV platform **Magis TV / Xuper** (`com.xuper.netxxus`). This tool is the result of reverse engineering the Magis TV Android APK for personal educational and research purposes only. No media files, streams, or server infrastructure are provided, hosted, or redistributed by this project or its author.

## License

For educational and research purposes only.
