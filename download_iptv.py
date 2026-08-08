#!/usr/bin/env python3
"""
Download Dragon Ball episodes from IPTV — 100% Python, no emulator needed.

Flow per episode:
1. Portal API play_vod() → license + media_code
2. Portal API get_slb() → Cloudflare CDN auth token
3. Direct HTTP download from CF CDN with Content-Auth + Content-License headers

Usage:
    python3 download_iptv.py              # All 153 episodes
    python3 download_iptv.py 1 5          # Episodes 1-5
    python3 download_iptv.py 10           # Episode 10 only
"""
import sys
import os
import json
import time
import re
from pathlib import Path

import requests

requests.packages.urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(__file__))
from iptv_client import IPTVClient

SERIES_ID = "3DE4A7E7C4EB4EFBABF927DBF1F7EF58"
OUT_DIR = Path(__file__).parent / "dragonball"
API_DELAY = 1.5  # seconds between portal API calls (rate limit respect)
DOWNLOAD_DELAY = 0.5  # seconds between downloads


def get_cf_vod_auth(client):
    """Get Cloudflare VOD CDN auth token from getSlbInfo."""
    slb = client.get_slb()
    for cdn in slb.get("cdn_list", []):
        if cdn.get("tag") != "vod":
            continue
        main_addr = cdn.get("main_addr", "")
        for u in cdn.get("url_list", []):
            auth = u.get("url", "")
            if "sign_type=cfl" in auth and u.get("tag") == "free":
                return main_addr.rstrip("/"), auth
    return None, None


def get_episode_info(client, episode):
    """Get media_code, license, and format for best available stream.

    Returns (media_code, license, video_format, error).
    video_format is 'mp4' or 'ts'.
    """
    play = client.play_vod(episode["contentId"], series_content_id=SERIES_ID)
    if "_error" in play:
        return None, None, None, play.get("_msg", play.get("_error"))

    try:
        ep_data = play["episodeList"][0]
    except (KeyError, IndexError):
        return None, None, None, "no episodeList"

    # Prefer h264/mp4
    for tm in ep_data.get("totalMovieList", []):
        for m in tm.get("movieList", []):
            if m.get("videoFormat") == "mp4" and m.get("encodeFormat") == "h264":
                mc = m["contentId"]
                lic = m["licenseList"][0]["license"]
                return mc, lic, "mp4", None

    # Fallback: take first available stream
    for tm in ep_data.get("totalMovieList", []):
        for m in tm.get("movieList", []):
            mc = m["contentId"]
            lic = m["licenseList"][0]["license"]
            vfmt = m.get("videoFormat", "mp4")
            fmt = f"{vfmt}/{m.get('encodeFormat')}"
            print(f"  WARNING: no h264/mp4, using {fmt}")
            return mc, lic, vfmt, None

    return None, None, None, "no streams found"


def download_episode(cdn_base, media_code, content_auth, content_license, out_path, video_format="mp4", retries=3):
    """Download from Cloudflare CDN (mp4 or ts)."""
    ext = "ts" if video_format == "ts" else "mp4"
    url = f"{cdn_base}/vod/{media_code}_media.{ext}"
    headers = {
        "Content-Auth": content_auth,
        "Content-License": content_license,
        "User-Agent": "Ranger/4.9.4-17294ac0",
        "App": os.environ.get("IPTV_APP_ID", ""),
        "App-Version": os.environ.get("IPTV_APK_VERSION", ""),
    }

    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=30)
            if r.status_code == 401:
                return 0, "401 Unauthorized (auth expired?)"
            if r.status_code == 404:
                return 0, "404 Not Found"
            r.raise_for_status()

            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            tmp_path = str(out_path) + ".tmp"

            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 / total
                        mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        print(f"\r  {mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)", end="", flush=True)

            print()

            if total and downloaded < total * 0.95:
                os.unlink(tmp_path)
                if attempt < retries - 1:
                    print(f"  Incomplete ({downloaded}/{total}), retry {attempt + 1}...")
                    time.sleep(2)
                    continue
                return downloaded, f"incomplete: {downloaded}/{total}"

            os.rename(tmp_path, out_path)
            return downloaded, None

        except requests.exceptions.ConnectionError as e:
            if attempt < retries - 1:
                print(f"\n  Connection error, retry {attempt + 1}...")
                time.sleep(3)
                continue
            return 0, str(e)
        except Exception as e:
            if attempt < retries - 1:
                print(f"\n  Error: {e}, retry {attempt + 1}...")
                time.sleep(2)
                continue
            return 0, str(e)

    return 0, "max retries exceeded"


def main():
    OUT_DIR.mkdir(exist_ok=True)

    start_ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end_ep = int(sys.argv[2]) if len(sys.argv) > 2 else (start_ep if len(sys.argv) == 2 else 153)

    print("=" * 50)
    print(f"  Dragon Ball IPTV Downloader (ep {start_ep}-{end_ep})")
    print("=" * 50)

    # Step 1: Initialize
    print("\n[1] Connecting to portal API...")
    client = IPTVClient()
    print(f"  userId={client.user_id}")
    time.sleep(API_DELAY)

    # Step 2: Get CDN auth
    print("\n[2] Getting Cloudflare VOD CDN auth...")
    cdn_base, cf_auth = get_cf_vod_auth(client)
    if not cdn_base:
        print("  ERROR: No Cloudflare VOD CDN found!")
        sys.exit(1)
    print(f"  CDN: {cdn_base}")
    exp_match = re.search(r"expired=(\d+)", cf_auth)
    if exp_match:
        exp_ts = int(exp_match.group(1))
        remaining_h = (exp_ts - time.time()) / 3600
        print(f"  Auth expires in: {remaining_h:.1f} hours")
    time.sleep(API_DELAY)

    # Step 3: Get episode list
    print("\n[3] Getting episode list...")
    all_eps = client.episodes(SERIES_ID)
    print(f"  Total: {len(all_eps)} episodes")
    time.sleep(API_DELAY)

    # Step 4: Download loop
    print(f"\n[4] Downloading episodes {start_ep}-{end_ep}...")

    stats = {"ok": 0, "fail": 0, "skip": 0}
    auth_refresh_counter = 0

    for i, ep in enumerate(all_eps):
        ep_num = int(ep.get("seriesNumber") or (i + 1))
        if ep_num < start_ep or ep_num > end_ep:
            continue

        # Check if already downloaded (either .mp4 or .ts)
        out_mp4 = OUT_DIR / f"ep{ep_num:03d}.mp4"
        out_ts = OUT_DIR / f"ep{ep_num:03d}.ts"
        if (out_mp4.exists() and out_mp4.stat().st_size > 1_000_000):
            print(f"\n  [{ep_num:03d}/153] SKIP ({out_mp4.stat().st_size / 1e6:.1f} MB)")
            stats["skip"] += 1
            continue
        if (out_ts.exists() and out_ts.stat().st_size > 1_000_000):
            print(f"\n  [{ep_num:03d}/153] SKIP ({out_ts.stat().st_size / 1e6:.1f} MB)")
            stats["skip"] += 1
            continue

        print(f"\n{'─' * 40}")
        print(f"  [{ep_num:03d}/153] {ep.get('name', ep_num)}")

        # Refresh CDN auth every 30 episodes (tokens expire in ~48h but be safe)
        auth_refresh_counter += 1
        if auth_refresh_counter > 30:
            print("  Refreshing CDN auth...")
            time.sleep(API_DELAY)
            cdn_base_new, cf_auth_new = get_cf_vod_auth(client)
            if cf_auth_new:
                cf_auth = cf_auth_new
                cdn_base = cdn_base_new
                auth_refresh_counter = 0
            time.sleep(API_DELAY)

        # Get episode license (with session recovery)
        time.sleep(API_DELAY)
        media_code, license_str, vfmt, err = get_episode_info(client, ep)
        if err:
            # Session expired? Re-activate and retry
            if "设备登录" in str(err) or "100083" in str(err) or "token" in str(err).lower():
                print(f"  Session expired, re-activating...")
                time.sleep(API_DELAY)
                client.activate()
                print(f"  New userId={client.user_id}")
                time.sleep(API_DELAY)
                cdn_base, cf_auth = get_cf_vod_auth(client)
                auth_refresh_counter = 0
                time.sleep(API_DELAY)
                media_code, license_str, vfmt, err = get_episode_info(client, ep)
            if err:
                print(f"  ERROR: {err}")
                stats["fail"] += 1
                continue

        out_file = OUT_DIR / f"ep{ep_num:03d}.{vfmt}"
        print(f"  media: {media_code[:16]}... ({vfmt})")

        # Download
        size, err = download_episode(cdn_base, media_code, cf_auth, license_str, out_file, video_format=vfmt)
        if err:
            print(f"  FAILED: {err}")
            # If auth expired, refresh and retry once
            if "401" in str(err) or "Unauthorized" in str(err):
                print("  Refreshing auth and retrying...")
                time.sleep(API_DELAY)
                cdn_base, cf_auth = get_cf_vod_auth(client)
                time.sleep(API_DELAY)
                _, license_str, vfmt, _ = get_episode_info(client, ep)
                time.sleep(API_DELAY)
                size, err = download_episode(cdn_base, media_code, cf_auth, license_str, out_file, video_format=vfmt)
                if err:
                    print(f"  RETRY FAILED: {err}")
                    stats["fail"] += 1
                    continue

            if err:
                stats["fail"] += 1
                continue

        print(f"  OK: {size / (1024*1024):.1f} MB")
        stats["ok"] += 1

        time.sleep(DOWNLOAD_DELAY)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"  Done! OK={stats['ok']} FAIL={stats['fail']} SKIP={stats['skip']}")
    total_size = sum(f.stat().st_size for f in OUT_DIR.iterdir() if f.name.startswith("ep") and f.suffix in (".mp4", ".ts"))
    print(f"  Total size: {total_size / (1024**3):.1f} GB")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
