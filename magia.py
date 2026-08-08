#!/usr/bin/env python3
"""
Interactive CLI for searching, browsing, downloading movies/series,
and getting live channel streaming URLs from IPTV services.

Usage:
    python3 magia.py                  Interactive mode (guided)
    python3 magia.py --help           Show this help

Requires: pip install pycryptodome requests
"""
import os
import re
import sys
import json
import time
import shutil
from pathlib import Path

import requests
requests.packages.urllib3.disable_warnings()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iptv_client import IPTVClient

# ─── ANSI colors ───
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"

API_DELAY = 1.5
DOWNLOAD_DELAY = 0.5
DEFAULT_OUT = Path(__file__).parent / os.environ.get("IPTV_DOWNLOAD_DIR", "downloads")

GENRES = [
    "Action", "Drama", "Adventure", "Crime", "Sci-Fi", "Cartoon", "Comedy",
    "Romance", "Animation", "Family", "Fantasy", "Thriller", "Horror",
    "History", "Mystery", "Documentary", "Reality-TV", "War", "Western",
    "Biography", "Music", "Sport",
]

COUNTRIES = [
    "United States", "Japan", "South Korea", "Mexico", "Brazil",
    "United Kingdom", "Spain", "Germany", "India", "Portugal",
]

# ─── UI ───
def clear():
    os.system("cls" if os.name == "nt" else "clear")

def banner():
    print(f"\n{C.CYAN}{C.BOLD}")
    print("  ███╗   ███╗ █████╗  ██████╗ ██╗ █████╗ ")
    print("  ████╗ ████║██╔══██╗██╔════╝ ██║██╔══██╗")
    print("  ██╔████╔██║███████║██║  ███╗██║███████║")
    print("  ██║╚██╔╝██║██╔══██║██║   ██║██║██╔══██║")
    print("  ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║██║  ██║")
    print("  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═╝")
    print(f"{C.RESET}")
    print(f"  {C.DIM}IPTV Media Tool — Search, Stream & Download{C.RESET}")
    print(f"  {C.DIM}{'─' * 45}{C.RESET}\n")

def section(title):
    w = min(shutil.get_terminal_size((80, 24)).columns - 4, 56)
    print(f"\n{C.CYAN}{C.BOLD}  ┌{'─' * w}┐{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  │ {title:<{w - 1}}│{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  └{'─' * w}┘{C.RESET}")

def info(msg):    print(f"  {C.BLUE}i{C.RESET}  {msg}")
def success(msg): print(f"  {C.GREEN}✓{C.RESET}  {msg}")
def warn(msg):    print(f"  {C.YELLOW}!{C.RESET}  {msg}")
def error(msg):   print(f"  {C.RED}x{C.RESET}  {msg}")

def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {C.MAGENTA}>{C.RESET} {prompt}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    return val or default

def ask_int(prompt, lo, hi, default=None):
    while True:
        val = ask(prompt, str(default) if default is not None else "")
        if val is None:
            return None
        try:
            n = int(val)
            if lo <= n <= hi:
                return n
            warn(f"Enter a number between {lo} and {hi}")
        except ValueError:
            warn("Enter a valid number")

def choose(prompt, options, allow_back=True):
    print()
    for i, (label, extra) in enumerate(options, 1):
        if extra:
            print(f"  {C.CYAN}{i:>3}{C.RESET}  {label}  {C.DIM}{extra}{C.RESET}")
        else:
            print(f"  {C.CYAN}{i:>3}{C.RESET}  {label}")
    if allow_back:
        print(f"  {C.DIM}  0  <- Back{C.RESET}")
    print()
    while True:
        val = ask(prompt)
        if val is None:
            return None, None
        try:
            n = int(val)
            if n == 0 and allow_back:
                return None, None
            if 1 <= n <= len(options):
                return n - 1, options[n - 1]
            warn(f"Enter 1-{len(options)}" + (" or 0 to go back" if allow_back else ""))
        except ValueError:
            warn("Enter a number")

def progress_bar(current, total, width=40, speed_mbps=0):
    if total <= 0:
        return
    pct = min(current / total, 1.0)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    cur_mb = current / (1024 * 1024)
    tot_mb = total / (1024 * 1024)
    speed_str = f" {speed_mbps:.1f} MB/s" if speed_mbps > 0 else ""
    print(f"\r  {C.GREEN}{bar}{C.RESET} {pct*100:5.1f}%  {cur_mb:.1f}/{tot_mb:.1f} MB{speed_str}", end="", flush=True)

def format_item(it):
    ptype = it.get("programType", "?")
    name = it.get("name", "?")
    if ptype in ("teleplay", "variety"):
        badge = f"{C.BLUE}[SERIE]{C.RESET}"
    elif ptype == "movie":
        badge = f"{C.GREEN}[PELI]{C.RESET} "
    else:
        badge = f"{C.DIM}[{ptype[:5]}]{C.RESET}"
    tags = it.get("tags", "")
    rt = it.get("releaseTime", "")
    year = rt[:4] if rt else ""
    score = it.get("score")
    meta = []
    if year:
        meta.append(year)
    if score:
        meta.append(f"★{score}")
    if tags:
        meta.append(tags[:35])
    return f"{badge} {name}", " | ".join(meta)


# ─── CDN ───
def get_cf_vod_auth(client):
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


# ─── Download engine ───
def resolve_streams(client, content_id, series_content_id=""):
    play = client.play_vod(content_id, series_content_id=series_content_id)
    if "_error" in play:
        return None, play.get("_msg", play.get("_error"))
    try:
        ep_data = play["episodeList"][0]
    except (KeyError, IndexError):
        return None, "No episode data"

    streams = []
    for tm in ep_data.get("totalMovieList", []):
        for m in tm.get("movieList", []):
            streams.append({
                "media_code": m["contentId"],
                "license": m["licenseList"][0]["license"],
                "video_format": m.get("videoFormat", "mp4"),
                "encode_format": m.get("encodeFormat", "h264"),
                "quality": m.get("quality", "?"),
            })
    if not streams:
        return None, "No streams"
    streams.sort(key=lambda s: (0 if s["encode_format"] == "h264" else 1))
    return streams, None


def download_file(cdn_base, media_code, content_auth, content_license,
                  out_path, video_format="mp4", retries=3):
    ext = "ts" if video_format == "ts" else "mp4"
    url = f"{cdn_base}/vod/{media_code}_media.{ext}"
    headers = {
        "Content-Auth": content_auth, "Content-License": content_license,
        "User-Agent": "Ranger/4.9.4-17294ac0",
        "App": os.environ.get("IPTV_APP_ID", ""), "App-Version": os.environ.get("IPTV_APK_VERSION", ""),
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=30)
            if r.status_code == 401:
                return 0, "401 Unauthorized"
            if r.status_code == 404:
                return 0, "404 Not Found"
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            tmp_path = str(out_path) + ".tmp"
            t0 = time.time()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.time() - t0
                    speed = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    progress_bar(downloaded, total, speed_mbps=speed)
            print()
            if total and downloaded < total * 0.95:
                os.unlink(tmp_path)
                if attempt < retries - 1:
                    warn(f"Incomplete, retry {attempt + 1}...")
                    time.sleep(2)
                    continue
                return downloaded, f"incomplete: {downloaded}/{total}"
            os.rename(tmp_path, out_path)
            return downloaded, None
        except requests.exceptions.ConnectionError:
            if attempt < retries - 1:
                print()
                warn(f"Connection error, retry {attempt + 1}...")
                time.sleep(3)
                continue
            return 0, "connection failed"
        except Exception as e:
            if attempt < retries - 1:
                print()
                warn(f"Error: {e}, retry {attempt + 1}...")
                time.sleep(2)
                continue
            return 0, str(e)
    return 0, "max retries"


def refresh_auth_if_needed(client, err, cdn_base, cf_auth):
    if "401" in str(err) or "设备登录" in str(err) or "100083" in str(err) or "token" in str(err).lower():
        warn("Session/auth expired, refreshing...")
        time.sleep(API_DELAY)
        client.activate()
        time.sleep(API_DELAY)
        return get_cf_vod_auth(client)
    return cdn_base, cf_auth


# ─── Item list with pagination (reusable) ───
def pick_from_list(items, title="Results", page_size=15):
    if not items:
        warn("No results")
        return None

    options = [format_item(it) for it in items]
    total_pages = (len(items) - 1) // page_size + 1
    page = 0

    while True:
        start = page * page_size
        end = min(start + page_size, len(items))
        print(f"\n  {C.DIM}─── {title} {start+1}-{end} of {len(items)} (page {page+1}/{total_pages}) ───{C.RESET}")
        for i in range(start, end):
            label, meta = options[i]
            num = i + 1
            if meta:
                print(f"  {C.CYAN}{num:>4}{C.RESET}  {label}  {C.DIM}{meta}{C.RESET}")
            else:
                print(f"  {C.CYAN}{num:>4}{C.RESET}  {label}")

        print(f"\n  {C.DIM}  [#] select  [n]ext  [p]rev  [b]ack{C.RESET}")
        val = ask("Select")
        if val is None or val.lower() == "b":
            return None
        elif val.lower() == "n" and page < total_pages - 1:
            page += 1
        elif val.lower() == "p" and page > 0:
            page -= 1
        else:
            try:
                n = int(val)
                if 1 <= n <= len(items):
                    return items[n - 1]
            except ValueError:
                pass


# ─── Search ───
def do_search(client):
    query = ask("Search")
    if not query:
        return None
    info(f"Searching '{query}'...")
    time.sleep(API_DELAY)
    sr = client.search(query, size=30)
    items = []
    for grp in sr.get("searchItemList", []):
        items.extend(grp.get("itemList", []))
    if not items:
        warn("No results found")
        return None
    total = sr.get("totalSize", len(items))
    section(f"Results for '{query}' ({total} total)")
    return pick_from_list(items, title=f"'{query}'")


# ─── Browse catalog (newest first) ───
def browse_catalog(client, query="s", label="Latest"):
    info(f"Loading {label}...")
    time.sleep(API_DELAY)
    page = 1
    all_items = []

    while True:
        sr = client.search(query, size=30, page=page)
        items = []
        for grp in sr.get("searchItemList", []):
            items.extend(grp.get("itemList", []))
        total = sr.get("totalSize", 0)
        if not items:
            if not all_items:
                warn("No content found")
                return None
            break
        all_items.extend(items)

        section(f"{label} — page {page} ({total:,} total in catalog)")
        options = [format_item(it) for it in items]
        for i, (label_txt, meta) in enumerate(options, 1):
            num = (page - 1) * 30 + i
            if meta:
                print(f"  {C.CYAN}{num:>4}{C.RESET}  {label_txt}  {C.DIM}{meta}{C.RESET}")
            else:
                print(f"  {C.CYAN}{num:>4}{C.RESET}  {label_txt}")

        print(f"\n  {C.DIM}  [#] select  [n]ext page  [b]ack{C.RESET}")
        val = ask("Select")
        if val is None or val.lower() == "b":
            return None
        elif val.lower() == "n":
            page += 1
            time.sleep(API_DELAY)
            continue
        else:
            try:
                n = int(val)
                if 1 <= n <= len(all_items):
                    return all_items[n - 1]
            except ValueError:
                pass

    return None


# ─── Browse by genre ───
def browse_by_genre(client):
    section("Browse by Genre")
    options = [(g, "") for g in GENRES]
    idx, _ = choose("Select genre", options)
    if idx is None:
        return None
    genre = GENRES[idx]
    return browse_catalog(client, query=genre, label=f"Genre: {genre}")


# ─── Browse by year ───
def browse_by_year(client):
    section("Browse by Year")
    years = [str(y) for y in range(2026, 1999, -1)]
    options = [(y, "") for y in years[:15]]
    idx, _ = choose("Select year", options)
    if idx is None:
        return None
    year = years[idx]
    return browse_catalog(client, query=year, label=f"Year: {year}")


# ─── Browse by country ───
def browse_by_country(client):
    section("Browse by Country")
    options = [(c, "") for c in COUNTRIES]
    idx, _ = choose("Select country", options)
    if idx is None:
        return None
    country = COUNTRIES[idx]
    return browse_catalog(client, query=country, label=f"Country: {country}")


# ─── Search by actor/director ───
def search_by_person(client):
    query = ask("Actor or director name")
    if not query:
        return None
    info(f"Searching person '{query}'...")
    time.sleep(API_DELAY)
    sp = client.search_resource_or_person(query, size=20)

    persons = sp.get("personResult", {}).get("personList", [])
    programs = sp.get("programResult", {}).get("programList", [])

    if persons:
        section(f"People matching '{query}'")
        p_options = [(p.get("name", "?"), "") for p in persons[:10]]
        idx, _ = choose("Select person (or 0 for direct results)", p_options)
        if idx is not None:
            person = persons[idx]
            pu_id = person.get("puId", "")
            info(f"Loading filmography for {person.get('name')}...")
            time.sleep(API_DELAY)
            filmography = client.items_by_person(pu_id, size=30)
            items = filmography.get("assetList") or filmography.get("list") or []
            if items:
                section(f"Filmography: {person.get('name')}")
                return pick_from_list(items, title=person.get("name", ""))
            else:
                warn("No filmography found")

    if programs:
        section(f"Content matching '{query}'")
        p_items = []
        for p in programs:
            p["programType"] = {"1": "movie", "2": "teleplay"}.get(p.get("type", ""), p.get("programType", "?"))
            p_items.append(p)
        return pick_from_list(p_items, title=f"'{query}'")

    warn("No results")
    return None


# ─── Recommendations ───
def show_recommendations(client):
    query = ask("Enter a movie/series name to get recommendations")
    if not query:
        return None
    info(f"Searching '{query}'...")
    time.sleep(API_DELAY)
    sr = client.search(query, size=5)
    items = []
    for grp in sr.get("searchItemList", []):
        items.extend(grp.get("itemList", []))
    if not items:
        warn("No results")
        return None

    section(f"Pick a title to find similar content")
    source = pick_from_list(items, title="Source")
    if not source:
        return None

    info(f"Finding content similar to '{source.get('name')}'...")
    time.sleep(API_DELAY)
    sim = client.similar(source["contentId"], rows=20)
    sim_items = sim.get("assetList") or sim.get("list") or []
    if not sim_items:
        warn("No recommendations found")
        return None
    section(f"Similar to: {source.get('name')}")
    return pick_from_list(sim_items, title="Recommendations")


# ─── Live TV ───
def handle_live(client, channel_item=None):
    if channel_item:
        show_live_url(client, channel_item.get("channelCode", ""),
                      channel_item.get("name", ""))
        return

    section("Live TV Channels")

    # Live categories
    info("Loading categories...")
    time.sleep(API_DELAY)
    cats = client.live_categories().get("recommendList", [])

    FEATURED_CATS = [
        (76182, "All Channels"),
        (76206, "Deportes"),
        (87034, "Vivo gratis"),
        (76205, "Cine y Series"),
        (77970, "Mas popular"),
        (76189, "24/7 Marathons"),
    ]
    cat_options = [(name, "") for _, name in FEATURED_CATS]
    # Add country categories
    country_cats = [(c.get("columnId"), c.get("name", "?")) for c in cats
                    if c.get("name") in ("Colombia", "Mexico", "Venezuela", "Chile",
                                         "Peru", "Ecuador", "Estados Unidos", "España")]
    if country_cats:
        cat_options.append((f"{C.BOLD}── By Country ──{C.RESET}", ""))
        for cid, name in country_cats:
            cat_options.append((f"  {name}", ""))
    cat_options.append((f"{C.BOLD}── Other ──{C.RESET}", ""))
    cat_options.append(("Search by name", "find a channel"))
    other_cats = [(c.get("columnId"), c.get("name", "?")) for c in cats
                  if c.get("columnId") not in [cid for cid, _ in FEATURED_CATS]
                  and c.get("name") not in ("Colombia", "Mexico", "Venezuela", "Chile",
                                            "Peru", "Ecuador", "Estados Unidos", "España")]

    idx, _ = choose("Select category", cat_options)
    if idx is None:
        return

    # Determine which columnId to load
    if idx < len(FEATURED_CATS):
        col_id = FEATURED_CATS[idx][0]
        cat_name = FEATURED_CATS[idx][1]
    elif idx == len(cat_options) - 1:
        # Search by name
        _live_search(client)
        return
    else:
        # Country or separator
        label = cat_options[idx][0].strip()
        if "──" in label:
            return
        # Find matching category
        match = next((c for c in cats if c.get("name") == label), None)
        if not match:
            return
        col_id = match["columnId"]
        cat_name = label

    info(f"Loading {cat_name}...")
    time.sleep(API_DELAY)
    ld = client.live_data(column_id=col_id, size=500)
    channels = ld.get("channelList", [])
    if not channels:
        warn("No channels in this category")
        return

    success(f"{len(channels)} channels")
    _browse_channels(client, channels, cat_name)


def _live_search(client):
    query = ask("Channel name")
    if not query:
        return
    info("Loading all channels...")
    time.sleep(API_DELAY)
    ld = client.live_data(size=1000)
    channels = ld.get("channelList", [])
    filtered = [ch for ch in channels if query.lower() in ch.get("name", "").lower()]
    if not filtered:
        warn(f"No channels matching '{query}'")
        return
    success(f"{len(filtered)} channels matching '{query}'")
    _browse_channels(client, filtered, f"Search: {query}")


def _browse_channels(client, channels, title):
    page_size = 20
    page = 0
    total_pages = (len(channels) - 1) // page_size + 1

    while True:
        start = page * page_size
        end = min(start + page_size, len(channels))
        print(f"\n  {C.DIM}─── {title} {start+1}-{end} of {len(channels)} (page {page+1}/{total_pages}) ───{C.RESET}")
        for i, ch in enumerate(channels[start:end], start + 1):
            name = ch.get("name", "?")
            num = ch.get("channelNumber", "")
            print(f"  {C.CYAN}{i:>4}{C.RESET}  {name}  {C.DIM}#{num}{C.RESET}")

        print(f"\n  {C.DIM}  [#] select  [n]ext  [p]rev  [b]ack{C.RESET}")
        val = ask("Select")
        if val is None or val.lower() == "b":
            return
        elif val.lower() == "n" and page < total_pages - 1:
            page += 1
        elif val.lower() == "p" and page > 0:
            page -= 1
        else:
            try:
                n = int(val)
                if 1 <= n <= len(channels):
                    ch = channels[n - 1]
                    show_live_url(client, ch["channelCode"], ch.get("name", ""))
            except ValueError:
                pass


def show_live_url(client, channel_code, channel_name):
    info(f"Getting stream for: {channel_name}...")
    time.sleep(API_DELAY)

    live = client.play_live(channel_code)
    addrs = live.get("liveAddressList", [])
    if not addrs:
        error("Could not get stream info")
        return

    section(f"Live: {channel_name}")

    addr = addrs[0]
    license_str = addr.get("license", "")

    print(f"""
  {C.BOLD}Channel:{C.RESET}     {channel_name}
  {C.BOLD}Play Code:{C.RESET}   {addr.get('playCode', channel_code)}
  {C.BOLD}Format:{C.RESET}      {addr.get('AVFormat', 'ts')}
  {C.BOLD}CDN Type:{C.RESET}    {addr.get('cdnType', '?')}

  {C.BOLD}License:{C.RESET}
  {C.DIM}{license_str}{C.RESET}""")

    seen = set()
    qualities = []
    for a in addrs:
        pc = a.get("playCode", "")
        if pc in seen:
            continue
        seen.add(pc)
        q = "HD" if "720" in pc else "SD" if "480" in pc else "FHD" if "fhd" in pc.lower() else "?"
        qualities.append((pc, q))

    if len(qualities) > 1:
        print(f"\n  {C.BOLD}Qualities:{C.RESET}")
        for pc, q in qualities:
            print(f"    {C.CYAN}-{C.RESET} {pc}  {C.DIM}({q}){C.RESET}")

    print(f"""
  {C.YELLOW}Note:{C.RESET} Live streams need SLB resolution for direct playback.
        Use these credentials with the IPTV app or a compatible player.
""")


# ─── Detail view ───
def show_detail(client, item):
    content_id = item["contentId"]
    name = item.get("name", "?")
    ptype = item.get("programType", "?")
    is_series = ptype in ("teleplay", "variety")

    section(f"{'Series' if is_series else 'Movie'}: {name}")

    info("Loading details...")
    time.sleep(API_DELAY)
    d = client.detail(content_id, type_="0" if is_series else "1")
    asset = d.get("assetData", d)

    year = (asset.get("releaseTime") or item.get("releaseTime") or "")[:4]
    score = asset.get("score") or item.get("score", "")
    tags = asset.get("tags") or item.get("tags", "")
    director = asset.get("director") or item.get("director", "")
    actors = asset.get("actorDisplay") or item.get("actorDisplay", "")
    desc = asset.get("description") or item.get("description", "")
    country = asset.get("originalCountry") or item.get("originalCountry", "")
    duration = asset.get("duration") or item.get("duration", "")

    if year:     print(f"  {C.BOLD}Year:{C.RESET}      {year}")
    if score:    print(f"  {C.BOLD}Score:{C.RESET}     {score}")
    if tags:     print(f"  {C.BOLD}Genre:{C.RESET}     {tags}")
    if country:  print(f"  {C.BOLD}Country:{C.RESET}   {country}")
    if duration: print(f"  {C.BOLD}Duration:{C.RESET}  {duration}")
    if director: print(f"  {C.BOLD}Director:{C.RESET}  {director}")
    if actors:   print(f"  {C.BOLD}Cast:{C.RESET}      {actors[:80]}")
    if desc:     print(f"\n  {C.DIM}{desc[:200]}{C.RESET}")

    if is_series:
        eps = asset.get("simpleProgramList", [])
        if eps:
            print(f"\n  {C.BOLD}Episodes:{C.RESET}  {len(eps)}")

    print()


# ─── Series handler ───
def handle_series(client, item, cdn_base, cf_auth, out_dir):
    content_id = item["contentId"]
    name = item.get("name", "Series")

    section(f"Series: {name}")

    # Show basic info inline
    tags = item.get("tags", "")
    score = item.get("score", "")
    year = (item.get("releaseTime") or "")[:4]
    if any([tags, score, year]):
        parts = []
        if year: parts.append(year)
        if score: parts.append(f"★{score}")
        if tags: parts.append(tags[:50])
        print(f"  {C.DIM}{' | '.join(parts)}{C.RESET}")
        print()

    info("Loading episodes...")
    time.sleep(API_DELAY)
    episodes = client.episodes(content_id)
    if not episodes:
        error("No episodes found")
        return
    success(f"Found {len(episodes)} episodes")

    safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')
    series_dir = out_dir / safe_name

    options = [
        ("Download ALL episodes", f"{len(episodes)} eps -> {series_dir.name}/"),
        ("Download a range", "e.g. episodes 1-10"),
        ("Download a single episode", "pick one"),
        ("Browse episode list", "see all episodes"),
        ("View details", "full info about this series"),
    ]
    idx, _ = choose("What do you want to do?", options)
    if idx is None:
        return

    if idx == 4:
        show_detail(client, item)
        return

    if idx == 3:
        page_size = 20
        page = 0
        total_pages = (len(episodes) - 1) // page_size + 1
        while True:
            start = page * page_size
            end = min(start + page_size, len(episodes))
            print(f"\n  {C.DIM}─── Episodes {start+1}-{end} of {len(episodes)} (page {page+1}/{total_pages}) ───{C.RESET}")
            for ep in episodes[start:end]:
                ep_num = ep.get("seriesNumber") or "?"
                ep_name = ep.get("name", "")
                q = ep.get("quality", "")
                print(f"    {C.CYAN}{ep_num:>4}{C.RESET}  {ep_name}  {C.DIM}{q}{C.RESET}")
            print()
            nav = ask("[n]ext / [p]rev / [d]ownload / [b]ack", "n")
            if nav is None or nav.lower() == "b":
                return
            elif nav.lower() == "n" and page < total_pages - 1:
                page += 1
            elif nav.lower() == "p" and page > 0:
                page -= 1
            elif nav.lower() == "d":
                break
        idx = 0

    if idx == 0:
        start_ep, end_ep = 1, len(episodes)
    elif idx == 1:
        start_ep = ask_int(f"From episode (1-{len(episodes)})", 1, len(episodes), 1)
        if start_ep is None: return
        end_ep = ask_int(f"To episode ({start_ep}-{len(episodes)})", start_ep, len(episodes), len(episodes))
        if end_ep is None: return
    elif idx == 2:
        start_ep = ask_int(f"Episode number (1-{len(episodes)})", 1, len(episodes))
        if start_ep is None: return
        end_ep = start_ep
    else:
        start_ep, end_ep = 1, len(episodes)

    series_dir.mkdir(parents=True, exist_ok=True)

    section(f"Downloading {name}: ep {start_ep}-{end_ep}")
    info(f"Output: {series_dir}")
    print()

    stats = {"ok": 0, "fail": 0, "skip": 0}
    auth_counter = 0
    cur_auth, cur_base = cf_auth, cdn_base

    for i, ep in enumerate(episodes):
        ep_num = int(ep.get("seriesNumber") or (i + 1))
        if ep_num < start_ep or ep_num > end_ep:
            continue

        existing = [f for f in series_dir.glob(f"ep{ep_num:03d}.*")
                     if f.suffix in (".mp4", ".ts") and f.stat().st_size > 1_000_000]
        if existing:
            print(f"  {C.DIM}[{ep_num:03d}/{len(episodes)}] SKIP ({existing[0].stat().st_size / 1e6:.1f} MB){C.RESET}")
            stats["skip"] += 1
            continue

        print(f"\n  {C.BOLD}[{ep_num:03d}/{len(episodes)}]{C.RESET} {ep.get('name', str(ep_num))}")

        auth_counter += 1
        if auth_counter > 30:
            info("Refreshing CDN auth...")
            time.sleep(API_DELAY)
            new_base, new_auth = get_cf_vod_auth(client)
            if new_auth:
                cur_auth, cur_base = new_auth, new_base
                auth_counter = 0
            time.sleep(API_DELAY)

        time.sleep(API_DELAY)
        streams, err = resolve_streams(client, ep["contentId"], series_content_id=content_id)
        if err:
            cur_base, cur_auth = refresh_auth_if_needed(client, err, cur_base, cur_auth)
            auth_counter = 0
            time.sleep(API_DELAY)
            streams, err = resolve_streams(client, ep["contentId"], series_content_id=content_id)
            if err:
                error(f"Failed: {err}")
                stats["fail"] += 1
                continue

        s = streams[0]
        out_file = series_dir / f"ep{ep_num:03d}.{s['video_format']}"

        size, dl_err = download_file(cur_base, s["media_code"], cur_auth, s["license"],
                                     out_file, video_format=s["video_format"])
        if dl_err and "401" in str(dl_err):
            cur_base, cur_auth = get_cf_vod_auth(client)
            time.sleep(API_DELAY)
            streams, _ = resolve_streams(client, ep["contentId"], series_content_id=content_id)
            if streams:
                s = streams[0]
                time.sleep(API_DELAY)
                size, dl_err = download_file(cur_base, s["media_code"], cur_auth, s["license"],
                                             out_file, video_format=s["video_format"])
        if dl_err:
            error(f"FAILED: {dl_err}")
            stats["fail"] += 1
            continue

        success(f"{size / (1024*1024):.1f} MB")
        stats["ok"] += 1
        time.sleep(DOWNLOAD_DELAY)

    section("Download Complete")
    total_size = sum(f.stat().st_size for f in series_dir.iterdir()
                     if f.suffix in (".mp4", ".ts"))
    print(f"""
  {C.GREEN}Downloaded:{C.RESET}  {stats['ok']}
  {C.YELLOW}Skipped:{C.RESET}    {stats['skip']}
  {C.RED}Failed:{C.RESET}     {stats['fail']}
  {C.BLUE}Total size:{C.RESET} {total_size / (1024**3):.2f} GB
  {C.DIM}{series_dir}{C.RESET}
""")


# ─── Movie handler ───
def handle_movie(client, item, cdn_base, cf_auth, out_dir):
    content_id = item["contentId"]
    name = item.get("name", "Movie")

    section(f"Movie: {name}")

    # Show basic info inline
    tags = item.get("tags", "")
    director = item.get("director", "")
    actors = item.get("actorDisplay", "")
    score = item.get("score", "")
    year = (item.get("releaseTime") or "")[:4]
    if any([tags, director, year, score]):
        if year:     print(f"  {C.BOLD}Year:{C.RESET}      {year}")
        if score:    print(f"  {C.BOLD}Score:{C.RESET}     {score}")
        if tags:     print(f"  {C.BOLD}Genre:{C.RESET}     {tags}")
        if director: print(f"  {C.BOLD}Director:{C.RESET}  {director}")
        if actors:   print(f"  {C.BOLD}Cast:{C.RESET}      {actors[:60]}")
        print()

    options = [
        ("Download", "download the movie file"),
        ("View details", "full info (cast, description, streams)"),
    ]
    idx, _ = choose("What do you want to do?", options)
    if idx is None:
        return

    if idx == 1:
        show_detail(client, item)
        cont = ask("Download this movie? (y/N)", "n")
        if not cont or cont.lower() != "y":
            return

    info("Getting streams...")
    time.sleep(API_DELAY)

    streams, err = resolve_streams(client, content_id)
    if err:
        error(f"Failed: {err}")
        return

    print(f"  {C.BOLD}Available streams:{C.RESET}")
    for i, s in enumerate(streams, 1):
        print(f"    {C.CYAN}{i}{C.RESET}  {s['encode_format']}/{s['video_format']}  {C.DIM}{s['quality']}{C.RESET}")

    stream_idx = 0
    if len(streams) > 1:
        val = ask(f"Select stream (1-{len(streams)})", "1")
        if val is None: return
        try:
            stream_idx = max(0, min(int(val) - 1, len(streams) - 1))
        except ValueError:
            pass

    s = streams[stream_idx]
    safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')
    out_file = out_dir / f"{safe_name}.{s['video_format']}"

    if out_file.exists() and out_file.stat().st_size > 1_000_000:
        warn(f"Already exists: {out_file.name} ({out_file.stat().st_size / 1e6:.1f} MB)")
        if (ask("Overwrite? (y/N)", "n") or "").lower() != "y":
            return

    section(f"Downloading: {name}")
    info(f"Format: {s['encode_format']}/{s['video_format']} {s['quality']}")
    info(f"Output: {out_file}")
    print()

    size, dl_err = download_file(cdn_base, s["media_code"], cf_auth, s["license"],
                                 out_file, video_format=s["video_format"])
    if dl_err and "401" in str(dl_err):
        cdn_base, cf_auth = get_cf_vod_auth(client)
        time.sleep(API_DELAY)
        streams, _ = resolve_streams(client, content_id)
        if streams:
            s = streams[min(stream_idx, len(streams) - 1)]
            size, dl_err = download_file(cdn_base, s["media_code"], cf_auth, s["license"],
                                         out_file, video_format=s["video_format"])
    if dl_err:
        error(f"Download failed: {dl_err}")
        return
    print()
    success(f"Downloaded: {out_file.name} ({size / (1024*1024):.1f} MB)")


# ─── Help ───
def show_help():
    section("How to use Magia")
    print(f"""
  {C.BOLD}Magia{C.RESET} is an interactive IPTV tool.

  {C.CYAN}--- Menu Options ---{C.RESET}

  {C.BOLD}1. Search{C.RESET}           Search by name. "dragon ball", "naruto", "broly"
  {C.BOLD}2. Latest{C.RESET}           Browse newest content (movies + series)
  {C.BOLD}3. By Genre{C.RESET}         Action, Comedy, Horror, Anime, Sci-Fi...
  {C.BOLD}4. By Year{C.RESET}          Filter by release year (2026, 2025...)
  {C.BOLD}5. By Country{C.RESET}       Japan, South Korea, USA, Mexico...
  {C.BOLD}6. By Actor{C.RESET}         Find content by actor or director name
  {C.BOLD}7. Recommendations{C.RESET}  "If you liked X, try Y"
  {C.BOLD}8. Live TV{C.RESET}          1000+ channels by category/country

  {C.CYAN}--- Content Types ---{C.RESET}

  {C.GREEN}[PELI]{C.RESET}  Movie   -> select quality -> downloads immediately
  {C.BLUE}[SERIE]{C.RESET} Series  -> pick episodes (all/range/single) -> downloads
  {C.YELLOW}[LIVE]{C.RESET}  Channel -> shows play code + license for external player

  {C.CYAN}--- Authentication ---{C.RESET}

  {C.BOLD}Free tier:{C.RESET}  auto-activates, most content available
  {C.BOLD}Login:{C.RESET}     email + encrypted password (for premium)

  {C.CYAN}--- Tips ---{C.RESET}

  Enter {C.BOLD}0{C.RESET} at any menu to go back
  Press {C.BOLD}Ctrl+C{C.RESET} to exit
  Downloaded episodes are auto-skipped on re-run
  CDN auth refreshes every 30 episodes automatically
""")


# ─── Route selected item ───
def handle_item(client, item, cdn_base, cf_auth, out_dir):
    if item is None:
        return
    ptype = item.get("programType", "")
    if ptype in ("teleplay", "variety"):
        handle_series(client, item, cdn_base, cf_auth, out_dir)
    else:
        handle_movie(client, item, cdn_base, cf_auth, out_dir)


# ─── First-run setup wizard ───
REQUIRED_VARS = [
    ("IPTV_3DES_KEY",        "3DES Key (48 hex chars)"),
    ("IPTV_HOSTS",           "API Hosts (comma-separated, e.g. host1.com,host2.com)"),
    ("IPTV_APP_ID",          "App ID (e.g. com.android.msandroid)"),
    ("IPTV_APK_VERSION",     "APK Version (e.g. 49902)"),
    ("IPTV_DEVICE_SN",       "Device SN (serial number hash)"),
    ("IPTV_DEVICE_DRM_ID",   "Device DRM ID"),
    ("IPTV_DEVICE_TOKEN",    "Device Token (Firebase token)"),
    ("IPTV_DEVICE_RESERVE1", "Device Reserve1 (hex-encoded field)"),
]

OPTIONAL_VARS = [
    ("IPTV_USERNAME",     "Login email (leave empty to skip)"),
    ("IPTV_PASSWORD",     "Encrypted password (leave empty to skip)"),
    ("IPTV_DOWNLOAD_DIR", "Download directory"),
]

def env_is_ready():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return False, "missing"
    for var, _ in REQUIRED_VARS:
        if not os.environ.get(var, ""):
            return False, "incomplete"
    return True, "ok"

def run_setup(reason):
    env_path = Path(__file__).parent / ".env"

    section("First-Run Setup")

    if reason == "missing":
        print(f"""
  {C.BOLD}No .env file found.{C.RESET}
  {C.DIM}Magia needs credentials to connect to the IPTV portal.{C.RESET}
  {C.DIM}These values come from APK analysis (see README for details).{C.RESET}
""")
        print(f"  {C.YELLOW}Two options:{C.RESET}")
        print(f"    {C.CYAN}1{C.RESET}  Fill in the values now (interactive wizard)")
        print(f"    {C.CYAN}2{C.RESET}  Create a blank .env template to edit manually")
        print()
        choice = ask("Choose (1/2)", "1")
        if choice == "2":
            example = Path(__file__).parent / ".env.example"
            if example.exists():
                import shutil as _sh
                _sh.copy2(example, env_path)
            else:
                env_path.write_text("\n".join(
                    f"{var}=" for var, _ in REQUIRED_VARS + OPTIONAL_VARS
                ) + "\n")
            print()
            success(f".env template created at {env_path}")
            info("Edit it with your values, then run magia again.")
            sys.exit(0)
    else:
        missing = [label for var, label in REQUIRED_VARS if not os.environ.get(var, "")]
        print(f"""
  {C.BOLD}.env found but missing required values:{C.RESET}
  {C.DIM}{', '.join(missing)}{C.RESET}
""")

    values = {}

    print(f"  {C.CYAN}{C.BOLD}-- Required --{C.RESET}")
    print()
    for var, label in REQUIRED_VARS:
        current = os.environ.get(var, "")
        while True:
            val = ask(label, current)
            if val is None:
                error("Setup cancelled.")
                sys.exit(0)
            if val:
                values[var] = val
                break
            warn("This field is required.")

    print()
    print(f"  {C.CYAN}{C.BOLD}-- Optional (press Enter to skip) --{C.RESET}")
    print()
    for var, label in OPTIONAL_VARS:
        current = os.environ.get(var, "")
        default = current if current else ("downloads" if var == "IPTV_DOWNLOAD_DIR" else "")
        val = ask(label, default)
        if val:
            values[var] = val

    lines = [
        "# IPTV Portal Configuration (generated by magia setup)",
        "",
        "# 3DES encryption key",
        f"IPTV_3DES_KEY={values.get('IPTV_3DES_KEY', '')}",
        "",
        "# API hosts",
        f"IPTV_HOSTS={values.get('IPTV_HOSTS', '')}",
        "",
        "# Device fingerprint",
        f"IPTV_DEVICE_SN={values.get('IPTV_DEVICE_SN', '')}",
        f"IPTV_DEVICE_DRM_ID={values.get('IPTV_DEVICE_DRM_ID', '')}",
        f"IPTV_DEVICE_TOKEN={values.get('IPTV_DEVICE_TOKEN', '')}",
        f"IPTV_DEVICE_RESERVE1={values.get('IPTV_DEVICE_RESERVE1', '')}",
        "",
        "# APK identity",
        f"IPTV_APP_ID={values.get('IPTV_APP_ID', '')}",
        f"IPTV_APK_VERSION={values.get('IPTV_APK_VERSION', '')}",
        "",
        "# Login credentials (optional)",
        f"IPTV_USERNAME={values.get('IPTV_USERNAME', '')}",
        f"IPTV_PASSWORD={values.get('IPTV_PASSWORD', '')}",
        "",
        "# Download settings",
        f"IPTV_DOWNLOAD_DIR={values.get('IPTV_DOWNLOAD_DIR', 'downloads')}",
        "",
    ]
    env_path.write_text("\n".join(lines))

    for k, v in values.items():
        os.environ[k] = v

    from iptv_client import _load_dotenv
    _load_dotenv()

    print()
    success(f".env saved to {env_path}")
    print()


# ─── Main ───
def main():
    clear()
    banner()

    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        return

    ready, reason = env_is_ready()
    if not ready:
        run_setup(reason)

    # Auth
    section("Authentication")
    options = [
        ("Free tier (no login)", "auto-activates, access to free content"),
        ("Login with account", "email + password for premium content"),
    ]
    auth_idx, _ = choose("Select authentication", options, allow_back=False)
    if auth_idx is None:
        return

    info("Connecting to IPTV portal...")

    if auth_idx == 0:
        client = IPTVClient()
        success(f"Connected (free tier) -- userId={client.user_id}")
    else:
        env_user = os.environ.get("IPTV_USERNAME", "")
        env_pass = os.environ.get("IPTV_PASSWORD", "")
        if env_user and env_pass:
            info(f"Using credentials from .env ({env_user})")
            username, password = env_user, env_pass
        else:
            username = ask("Email / username")
            if not username:
                return
            password = ask("Encrypted password (from app capture)")
        if not password:
            warn("Tip: The app encrypts passwords with DES before sending.")
            warn("Falling back to free tier...")
            client = IPTVClient()
            success(f"Connected (free tier) -- userId={client.user_id}")
        else:
            client = IPTVClient(auto_activate=False)
            result = client.login(username, password)
            if "_error" in result:
                error(f"Login failed: {result.get('_msg', result.get('_error'))}")
                warn("Falling back to free tier...")
                client = IPTVClient()
            else:
                success(f"Logged in -- userId={client.user_id}")

    # CDN auth
    info("Getting CDN authorization...")
    time.sleep(API_DELAY)
    cdn_base, cf_auth = get_cf_vod_auth(client)
    if cdn_base:
        exp_match = re.search(r"expired=(\d+)", cf_auth or "")
        if exp_match:
            remaining_h = (int(exp_match.group(1)) - time.time()) / 3600
            success(f"CDN ready -- auth valid for {remaining_h:.1f} hours")
        else:
            success("CDN ready")
    else:
        warn("No Cloudflare CDN found (downloads may not work)")

    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)

    # Main loop
    while True:
        section("Main Menu")
        menu = [
            (f"{C.BOLD}Search{C.RESET}",            "find by name"),
            (f"{C.BOLD}Latest{C.RESET}",            "browse newest movies & series"),
            (f"{C.BOLD}By Genre{C.RESET}",          "Action, Comedy, Horror, Anime..."),
            (f"{C.BOLD}By Year{C.RESET}",           "2026, 2025, 2024..."),
            (f"{C.BOLD}By Country{C.RESET}",        "Japan, South Korea, USA..."),
            (f"{C.BOLD}By Actor/Director{C.RESET}", "search by person"),
            (f"{C.BOLD}Recommendations{C.RESET}",   "similar to a title you like"),
            (f"{C.BOLD}Live TV{C.RESET}",           "1000+ channels by category"),
            (f"{C.BOLD}Help{C.RESET}",              "usage guide"),
            (f"{C.BOLD}Exit{C.RESET}",              ""),
        ]
        idx, _ = choose("Select", menu, allow_back=False)
        if idx is None or idx == 9:
            print(f"\n  {C.DIM}Bye!{C.RESET}\n")
            break

        if idx == 0:
            item = do_search(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 1:
            item = browse_catalog(client, query="s", label="Latest")
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 2:
            item = browse_by_genre(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 3:
            item = browse_by_year(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 4:
            item = browse_by_country(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 5:
            item = search_by_person(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 6:
            item = show_recommendations(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 7:
            handle_live(client)
        elif idx == 8:
            show_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {C.DIM}Interrupted. Bye!{C.RESET}\n")
        sys.exit(0)
