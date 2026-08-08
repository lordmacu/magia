#!/usr/bin/env python3
"""
Interactive CLI for searching, browsing, downloading movies/series,
and getting live channel streaming URLs from IPTV services.

Usage:
    python3 magia.py                  Interactive mode (guided)
    python3 magia.py --help           Show this help

Requires: pip install pycryptodome requests rich InquirerPy
"""
import os
import re
import sys
import json
import time
import shutil
import subprocess
from pathlib import Path

import requests
requests.packages.urllib3.disable_warnings()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.columns import Columns
from rich.rule import Rule
from rich.align import Align
from rich import box
from InquirerPy import inquirer
from InquirerPy.separator import Separator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iptv_client import IPTVClient

console = Console()

API_DELAY = 1.5
DOWNLOAD_DELAY = 0.5

def _env_dir():
    if (Path.cwd() / ".env").exists():
        return Path.cwd()
    return Path(__file__).parent

DEFAULT_OUT = _env_dir() / os.environ.get("IPTV_DOWNLOAD_DIR", "downloads")

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

BANNER = """[bold cyan]
  ███╗   ███╗ █████╗  ██████╗ ██╗ █████╗
  ████╗ ████║██╔══██╗██╔════╝ ██║██╔══██╗
  ██╔████╔██║███████║██║  ███╗██║███████║
  ██║╚██╔╝██║██╔══██║██║   ██║██║██╔══██║
  ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║██║  ██║
  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═╝
[/bold cyan]"""


# ─── UI helpers ───
def banner():
    console.print(BANNER)
    console.print("  [dim]IPTV Media Tool -- Search, Stream & Download[/dim]\n")

def section(title):
    console.print()
    console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan", padding=(0, 2)))

def info(msg):    console.print(f"  [blue]i[/blue]  {msg}")
def success(msg): console.print(f"  [green]>[/green]  {msg}")
def warn(msg):    console.print(f"  [yellow]![/yellow]  {msg}")
def error(msg):   console.print(f"  [red]x[/red]  {msg}")


def ask(prompt, default=""):
    try:
        return inquirer.text(message=prompt, default=default).execute()
    except (KeyboardInterrupt, EOFError):
        return None


def confirm(prompt, default=True):
    try:
        return inquirer.confirm(message=prompt, default=default).execute()
    except (KeyboardInterrupt, EOFError):
        return None


def select_menu(prompt, choices, back=True):
    items = []
    for label, hint in choices:
        name = f"{label}  [dim]{hint}[/dim]" if hint else label
        items.append({"name": name, "value": label})
    if back:
        items.append(Separator())
        items.append({"name": "[dim]<- Back[/dim]", "value": "__back__"})
    try:
        result = inquirer.select(
            message=prompt,
            choices=items,
            pointer=">",
            show_selected=True,
        ).execute()
        if result == "__back__":
            return None
        for i, (label, _) in enumerate(choices):
            if label == result:
                return i
        return None
    except (KeyboardInterrupt, EOFError):
        return None


def format_badge(ptype):
    if ptype in ("teleplay", "variety"):
        return "[bold blue]SERIE[/bold blue]"
    elif ptype == "movie":
        return "[bold green]MOVIE[/bold green]"
    return f"[dim]{ptype[:5]}[/dim]"


def format_meta(item):
    parts = []
    rt = item.get("releaseTime", "")
    year = rt[:4] if rt else ""
    if year:
        parts.append(year)
    score = item.get("score")
    if score:
        parts.append(f"[yellow]*{score}[/yellow]")
    tags = item.get("tags", "")
    if tags:
        parts.append(f"[dim]{tags[:35]}[/dim]")
    return " | ".join(parts)


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
            with Progress(
                "[progress.description]{task.description}",
                BarColumn(bar_width=40),
                "[progress.percentage]{task.percentage:>3.1f}%",
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Downloading", total=total)
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress.update(task, completed=downloaded)
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
                warn(f"Connection error, retry {attempt + 1}...")
                time.sleep(3)
                continue
            return 0, "connection failed"
        except Exception as e:
            if attempt < retries - 1:
                warn(f"Error: {e}, retry {attempt + 1}...")
                time.sleep(2)
                continue
            return 0, str(e)
    return 0, "max retries"


def _ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return True
    warn("ffmpeg not found, attempting to install...")
    platform = sys.platform
    try:
        if platform == "darwin":
            if shutil.which("brew"):
                subprocess.run(["brew", "install", "ffmpeg"], check=True)
            else:
                error("Install Homebrew first: https://brew.sh")
                return False
        elif platform.startswith("linux"):
            if shutil.which("apt-get"):
                subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], check=True)
            elif shutil.which("dnf"):
                subprocess.run(["sudo", "dnf", "install", "-y", "ffmpeg"], check=True)
            elif shutil.which("pacman"):
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"], check=True)
            elif shutil.which("pkg"):
                subprocess.run(["pkg", "install", "-y", "ffmpeg"], check=True)
            else:
                error("Could not detect package manager. Install ffmpeg manually.")
                return False
        elif platform == "win32":
            if shutil.which("choco"):
                subprocess.run(["choco", "install", "ffmpeg", "-y"], check=True)
            elif shutil.which("winget"):
                subprocess.run(["winget", "install", "Gyan.FFmpeg", "--accept-source-agreements"], check=True)
            else:
                error("Install ffmpeg manually: https://ffmpeg.org/download.html")
                return False
        else:
            error("Unsupported platform. Install ffmpeg manually.")
            return False
    except subprocess.CalledProcessError:
        error("ffmpeg installation failed. Install it manually.")
        return False
    if shutil.which("ffmpeg"):
        success("ffmpeg installed successfully")
        return True
    error("ffmpeg installation did not complete. Install it manually.")
    return False


def convert_ts_to_mp4(ts_path):
    mp4_path = ts_path.with_suffix(".mp4")
    info(f"Converting to MP4: {mp4_path.name}")
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(ts_path), "-map", "0", "-c", "copy", "-y", str(mp4_path)],
            capture_output=True, timeout=300,
        )
        if result.returncode == 0 and mp4_path.exists():
            ts_path.unlink()
            success(f"Converted: {mp4_path.name}")
            return mp4_path
        else:
            warn("Conversion failed, keeping .ts file")
            return ts_path
    except subprocess.TimeoutExpired:
        warn("Conversion timed out, keeping .ts file")
        return ts_path
    except FileNotFoundError:
        warn("ffmpeg not available, keeping .ts file")
        return ts_path


def open_folder(path):
    folder = path if path.is_dir() else path.parent
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


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

    total_pages = (len(items) - 1) // page_size + 1
    page = 0

    while True:
        start = page * page_size
        end = min(start + page_size, len(items))

        table = Table(
            title=f"{title} ({start+1}-{end} of {len(items)}) -- page {page+1}/{total_pages}",
            box=box.ROUNDED,
            border_style="dim",
            title_style="bold",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("#", style="cyan", width=5, justify="right")
        table.add_column("Type", width=7)
        table.add_column("Title", style="bold")
        table.add_column("Info", style="dim")

        for i in range(start, end):
            it = items[i]
            badge = format_badge(it.get("programType", "?"))
            meta = format_meta(it)
            table.add_row(str(i + 1), badge, it.get("name", "?"), meta)

        console.print()
        console.print(table)

        choices = []
        for i in range(start, end):
            it = items[i]
            choices.append({"name": f"{i+1}. {it.get('name', '?')}", "value": i})
        if page < total_pages - 1:
            choices.append(Separator())
            choices.append({"name": ">> Next page", "value": "__next__"})
        if page > 0:
            choices.append({"name": "<< Previous page", "value": "__prev__"})
        choices.append(Separator())
        choices.append({"name": "[dim]<- Back[/dim]", "value": "__back__"})

        try:
            val = inquirer.select(
                message="Select",
                choices=choices,
                pointer=">",
            ).execute()
        except (KeyboardInterrupt, EOFError):
            return None

        if val == "__back__":
            return None
        elif val == "__next__":
            page += 1
        elif val == "__prev__":
            page -= 1
        else:
            return items[val]


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

        table = Table(
            title=f"{label} -- page {page} ({total:,} total)",
            box=box.ROUNDED,
            border_style="dim",
            title_style="bold",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("#", style="cyan", width=5, justify="right")
        table.add_column("Type", width=7)
        table.add_column("Title", style="bold")
        table.add_column("Info", style="dim")

        for i, it in enumerate(items, 1):
            num = (page - 1) * 30 + i
            badge = format_badge(it.get("programType", "?"))
            meta = format_meta(it)
            table.add_row(str(num), badge, it.get("name", "?"), meta)

        console.print()
        console.print(table)

        choices = []
        for i, it in enumerate(items, 1):
            num = (page - 1) * 30 + i
            choices.append({"name": f"{num}. {it.get('name', '?')}", "value": num - 1})
        choices.append(Separator())
        choices.append({"name": ">> Next page", "value": "__next__"})
        choices.append({"name": "[dim]<- Back[/dim]", "value": "__back__"})

        try:
            val = inquirer.select(message="Select", choices=choices, pointer=">").execute()
        except (KeyboardInterrupt, EOFError):
            return None

        if val == "__back__":
            return None
        elif val == "__next__":
            page += 1
            time.sleep(API_DELAY)
            continue
        else:
            if 0 <= val < len(all_items):
                return all_items[val]

    return None


# ─── Browse by genre ───
def browse_by_genre(client):
    section("Browse by Genre")
    choices = [(g, "") for g in GENRES]
    idx = select_menu("Select genre", choices)
    if idx is None:
        return None
    genre = GENRES[idx]
    return browse_catalog(client, query=genre, label=f"Genre: {genre}")


# ─── Browse by year ───
def browse_by_year(client):
    section("Browse by Year")
    years = [str(y) for y in range(2026, 1999, -1)]
    choices = [(y, "") for y in years[:15]]
    idx = select_menu("Select year", choices)
    if idx is None:
        return None
    year = years[idx]
    return browse_catalog(client, query=year, label=f"Year: {year}")


# ─── Browse by country ───
def browse_by_country(client):
    section("Browse by Country")
    choices = [(c, "") for c in COUNTRIES]
    idx = select_menu("Select country", choices)
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
        p_choices = [(p.get("name", "?"), "") for p in persons[:10]]
        idx = select_menu("Select person (or back for direct results)", p_choices)
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

    section("Pick a title to find similar content")
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

    cat_choices = [(name, "") for _, name in FEATURED_CATS]
    country_cats = [(c.get("columnId"), c.get("name", "?")) for c in cats
                    if c.get("name") in ("Colombia", "Mexico", "Venezuela", "Chile",
                                         "Peru", "Ecuador", "Estados Unidos", "España")]
    for _, name in country_cats:
        cat_choices.append((f"  {name}", "by country"))
    cat_choices.append(("Search by name", "find a channel"))

    idx = select_menu("Select category", cat_choices)
    if idx is None:
        return

    if idx < len(FEATURED_CATS):
        col_id = FEATURED_CATS[idx][0]
        cat_name = FEATURED_CATS[idx][1]
    elif idx == len(cat_choices) - 1:
        _live_search(client)
        return
    else:
        country_idx = idx - len(FEATURED_CATS)
        if 0 <= country_idx < len(country_cats):
            col_id = country_cats[country_idx][0]
            cat_name = country_cats[country_idx][1]
        else:
            return

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

        table = Table(
            title=f"{title} ({start+1}-{end} of {len(channels)}) -- page {page+1}/{total_pages}",
            box=box.ROUNDED,
            border_style="dim",
            title_style="bold",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("#", style="cyan", width=5, justify="right")
        table.add_column("Channel", style="bold")
        table.add_column("Number", style="dim", justify="right")

        for i, ch in enumerate(channels[start:end], start + 1):
            table.add_row(str(i), ch.get("name", "?"), f"#{ch.get('channelNumber', '')}")

        console.print()
        console.print(table)

        choices = []
        for i, ch in enumerate(channels[start:end], start + 1):
            choices.append({"name": f"{i}. {ch.get('name', '?')}", "value": i})
        if page < total_pages - 1:
            choices.append(Separator())
            choices.append({"name": ">> Next page", "value": "__next__"})
        if page > 0:
            choices.append({"name": "<< Previous page", "value": "__prev__"})
        choices.append(Separator())
        choices.append({"name": "[dim]<- Back[/dim]", "value": "__back__"})

        try:
            val = inquirer.select(message="Select", choices=choices, pointer=">").execute()
        except (KeyboardInterrupt, EOFError):
            return

        if val == "__back__":
            return
        elif val == "__next__":
            page += 1
        elif val == "__prev__":
            page -= 1
        else:
            if 1 <= val <= len(channels):
                ch = channels[val - 1]
                show_live_url(client, ch["channelCode"], ch.get("name", ""))


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

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Channel", channel_name)
    table.add_row("Play Code", addr.get("playCode", channel_code))
    table.add_row("Format", addr.get("AVFormat", "ts"))
    table.add_row("CDN Type", addr.get("cdnType", "?"))
    console.print(table)

    console.print(f"\n  [bold]License:[/bold]\n  [dim]{license_str}[/dim]")

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
        console.print("\n  [bold]Qualities:[/bold]")
        for pc, q in qualities:
            console.print(f"    [cyan]-[/cyan] {pc}  [dim]({q})[/dim]")

    console.print(Panel(
        "Live streams need SLB resolution for direct playback.\n"
        "Use these credentials with the IPTV app or a compatible player.",
        border_style="yellow",
        title="Note",
        padding=(0, 1),
    ))


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

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    if year:     table.add_row("Year", year)
    if score:    table.add_row("Score", str(score))
    if tags:     table.add_row("Genre", tags)
    if country:  table.add_row("Country", country)
    if duration: table.add_row("Duration", str(duration))
    if director: table.add_row("Director", director)
    if actors:   table.add_row("Cast", actors[:80])
    console.print(table)

    if desc:
        console.print(Panel(desc[:300], title="Synopsis", border_style="dim", padding=(0, 1)))

    if is_series:
        eps = asset.get("simpleProgramList", [])
        if eps:
            console.print(f"\n  [bold]Episodes:[/bold] {len(eps)}")

    console.print()


# ─── Series handler ───
def handle_series(client, item, cdn_base, cf_auth, out_dir):
    content_id = item["contentId"]
    name = item.get("name", "Series")

    section(f"Series: {name}")

    tags = item.get("tags", "")
    score = item.get("score", "")
    year = (item.get("releaseTime") or "")[:4]
    if any([tags, score, year]):
        parts = []
        if year: parts.append(year)
        if score: parts.append(f"*{score}")
        if tags: parts.append(tags[:50])
        console.print(f"  [dim]{' | '.join(parts)}[/dim]\n")

    info("Loading episodes...")
    time.sleep(API_DELAY)
    episodes = client.episodes(content_id)
    if not episodes:
        error("No episodes found")
        return
    success(f"Found {len(episodes)} episodes")

    safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')
    series_dir = out_dir / safe_name

    choices = [
        ("Download ALL episodes", f"{len(episodes)} eps -> {safe_name}/"),
        ("Download a range", "e.g. episodes 1-10"),
        ("Download a single episode", "pick one"),
        ("Browse episode list", "see all episodes"),
        ("View details", "full info about this series"),
    ]
    idx = select_menu("What do you want to do?", choices)
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

            table = Table(
                title=f"Episodes {start+1}-{end} of {len(episodes)} -- page {page+1}/{total_pages}",
                box=box.ROUNDED,
                border_style="dim",
                title_style="bold",
                show_lines=False,
                padding=(0, 1),
            )
            table.add_column("#", style="cyan", width=5, justify="right")
            table.add_column("Episode", style="bold")
            table.add_column("Quality", style="dim")

            for ep in episodes[start:end]:
                ep_num = ep.get("seriesNumber") or "?"
                ep_name = ep.get("name", "")
                q = ep.get("quality", "")
                table.add_row(str(ep_num), ep_name, q)

            console.print()
            console.print(table)

            nav_choices = [
                ("Next page", ""),
                ("Previous page", ""),
                ("Download", "proceed to download"),
                ("Back", "return to menu"),
            ]
            nav = select_menu("Navigate", nav_choices, back=False)
            if nav is None or nav == 3:
                return
            elif nav == 0 and page < total_pages - 1:
                page += 1
            elif nav == 1 and page > 0:
                page -= 1
            elif nav == 2:
                break
        idx = 0

    if idx == 0:
        start_ep, end_ep = 1, len(episodes)
    elif idx == 1:
        val = ask(f"From episode (1-{len(episodes)})", "1")
        if val is None: return
        try: start_ep = max(1, min(int(val), len(episodes)))
        except ValueError: start_ep = 1
        val = ask(f"To episode ({start_ep}-{len(episodes)})", str(len(episodes)))
        if val is None: return
        try: end_ep = max(start_ep, min(int(val), len(episodes)))
        except ValueError: end_ep = len(episodes)
    elif idx == 2:
        val = ask(f"Episode number (1-{len(episodes)})")
        if val is None: return
        try: start_ep = max(1, min(int(val), len(episodes)))
        except ValueError: start_ep = 1
        end_ep = start_ep
    else:
        start_ep, end_ep = 1, len(episodes)

    series_dir.mkdir(parents=True, exist_ok=True)

    section(f"Downloading {name}: ep {start_ep}-{end_ep}")
    info(f"Output: {series_dir}")
    console.print()

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
            console.print(f"  [dim][{ep_num:03d}/{len(episodes)}] SKIP ({existing[0].stat().st_size / 1e6:.1f} MB)[/dim]")
            stats["skip"] += 1
            continue

        console.print(f"\n  [bold][{ep_num:03d}/{len(episodes)}][/bold] {ep.get('name', str(ep_num))}")

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
        if out_file.suffix == ".ts":
            convert_ts_to_mp4(out_file)
        stats["ok"] += 1
        time.sleep(DOWNLOAD_DELAY)

    section("Download Complete")
    total_size = sum(f.stat().st_size for f in series_dir.iterdir()
                     if f.suffix in (".mp4", ".ts"))

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column("Stat", style="bold")
    summary.add_column("Value")
    summary.add_row("[green]Downloaded[/green]", str(stats["ok"]))
    summary.add_row("[yellow]Skipped[/yellow]", str(stats["skip"]))
    summary.add_row("[red]Failed[/red]", str(stats["fail"]))
    summary.add_row("[blue]Total size[/blue]", f"{total_size / (1024**3):.2f} GB")
    summary.add_row("[dim]Location[/dim]", str(series_dir))
    console.print(summary)

    if confirm("Open download folder?", default=True):
        open_folder(series_dir)


# ─── Movie handler ───
def handle_movie(client, item, cdn_base, cf_auth, out_dir):
    content_id = item["contentId"]
    name = item.get("name", "Movie")

    section(f"Movie: {name}")

    tags = item.get("tags", "")
    director = item.get("director", "")
    actors = item.get("actorDisplay", "")
    score = item.get("score", "")
    year = (item.get("releaseTime") or "")[:4]
    if any([tags, director, year, score]):
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Key", style="bold cyan")
        table.add_column("Value")
        if year:     table.add_row("Year", year)
        if score:    table.add_row("Score", str(score))
        if tags:     table.add_row("Genre", tags)
        if director: table.add_row("Director", director)
        if actors:   table.add_row("Cast", actors[:60])
        console.print(table)

    choices = [
        ("Download", "download the movie file"),
        ("View details", "full info (cast, description, streams)"),
    ]
    idx = select_menu("What do you want to do?", choices)
    if idx is None:
        return

    if idx == 1:
        show_detail(client, item)
        if not confirm("Download this movie?", default=False):
            return

    info("Getting streams...")
    time.sleep(API_DELAY)

    streams, err = resolve_streams(client, content_id)
    if err:
        error(f"Failed: {err}")
        return

    if len(streams) > 1:
        stream_choices = []
        for s in streams:
            stream_choices.append((f"{s['encode_format']}/{s['video_format']}  {s['quality']}", ""))
        stream_idx = select_menu("Select stream quality", stream_choices, back=False)
        if stream_idx is None:
            stream_idx = 0
    else:
        stream_idx = 0
        info(f"Stream: {streams[0]['encode_format']}/{streams[0]['video_format']} {streams[0]['quality']}")

    s = streams[stream_idx]
    safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')
    out_file = out_dir / f"{safe_name}.{s['video_format']}"

    if out_file.exists() and out_file.stat().st_size > 1_000_000:
        warn(f"Already exists: {out_file.name} ({out_file.stat().st_size / 1e6:.1f} MB)")
        if not confirm("Overwrite?", default=False):
            return

    section(f"Downloading: {name}")
    info(f"Format: {s['encode_format']}/{s['video_format']} {s['quality']}")
    info(f"Output: {out_file}")
    console.print()

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
    console.print()
    if out_file.suffix == ".ts":
        out_file = convert_ts_to_mp4(out_file)
    success(f"Downloaded: {out_file.name} ({size / (1024*1024):.1f} MB)")
    if confirm("Open download folder?", default=True):
        open_folder(out_file)


# ─── Help ───
def show_help():
    section("How to use Magia")

    table = Table(
        title="Menu Options",
        box=box.ROUNDED,
        border_style="cyan",
        title_style="bold cyan",
        padding=(0, 2),
    )
    table.add_column("Option", style="bold")
    table.add_column("Description")
    table.add_row("Search", "Search by name: 'dragon ball', 'naruto', 'broly'")
    table.add_row("Latest", "Browse newest content (movies + series)")
    table.add_row("By Genre", "Action, Comedy, Horror, Anime, Sci-Fi...")
    table.add_row("By Year", "Filter by release year (2026, 2025...)")
    table.add_row("By Country", "Japan, South Korea, USA, Mexico...")
    table.add_row("By Actor", "Find content by actor or director name")
    table.add_row("Recommendations", "'If you liked X, try Y'")
    table.add_row("Live TV", "1000+ channels by category/country")
    console.print(table)

    table2 = Table(
        title="Content Types",
        box=box.ROUNDED,
        border_style="green",
        title_style="bold green",
        padding=(0, 2),
    )
    table2.add_column("Badge", width=8)
    table2.add_column("Type")
    table2.add_column("Action")
    table2.add_row("[green]MOVIE[/green]", "Movie", "Select quality -> downloads immediately")
    table2.add_row("[blue]SERIE[/blue]", "Series", "Pick episodes (all/range/single) -> downloads")
    table2.add_row("[yellow]LIVE[/yellow]", "Channel", "Shows play code + license for player")
    console.print(table2)

    console.print(Panel(
        "[bold]Free tier:[/bold]  auto-activates, most content available\n"
        "[bold]Login:[/bold]     email + encrypted password (for premium)\n\n"
        "Press [bold]Ctrl+C[/bold] to exit at any time\n"
        "Downloaded episodes are auto-skipped on re-run\n"
        "CDN auth refreshes every 30 episodes automatically",
        title="Tips",
        border_style="dim",
        padding=(0, 2),
    ))


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
    env_path = _env_dir() / ".env"
    if not env_path.exists():
        return False, "missing"
    for var, _ in REQUIRED_VARS:
        if not os.environ.get(var, ""):
            return False, "incomplete"
    return True, "ok"

def run_setup(reason):
    env_path = _env_dir() / ".env"

    section("First-Run Setup")

    if reason == "missing":
        console.print(Panel(
            "[bold]No .env file found.[/bold]\n\n"
            "Magia needs credentials to connect to the IPTV portal.\n"
            "These values come from APK analysis (see README for details).",
            border_style="yellow",
            padding=(1, 2),
        ))

        setup_choices = [
            ("Fill in the values now", "interactive wizard"),
            ("Create a blank .env template", "edit manually later"),
        ]
        choice = select_menu("Choose setup method", setup_choices, back=False)
        if choice == 1:
            example = _env_dir() / ".env.example"
            if example.exists():
                import shutil as _sh
                _sh.copy2(example, env_path)
            else:
                env_path.write_text("\n".join(
                    f"{var}=" for var, _ in REQUIRED_VARS + OPTIONAL_VARS
                ) + "\n")
            console.print()
            success(f".env template created at {env_path}")
            info("Edit it with your values, then run magia again.")
            sys.exit(0)
    else:
        missing = [label for var, label in REQUIRED_VARS if not os.environ.get(var, "")]
        console.print(Panel(
            "[bold].env found but missing required values:[/bold]\n\n"
            + "\n".join(f"  - {m}" for m in missing),
            border_style="yellow",
            padding=(1, 2),
        ))

    values = {}

    console.print(Rule("Required", style="cyan"))
    console.print()
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

    console.print()
    console.print(Rule("Optional (press Enter to skip)", style="dim"))
    console.print()
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

    console.print()
    success(f".env saved to {env_path}")
    console.print()


# ─── Main ───
def main():
    os.system("cls" if os.name == "nt" else "clear")
    banner()

    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        return

    ready, reason = env_is_ready()
    if not ready:
        run_setup(reason)

    _ensure_ffmpeg()

    # Auth
    section("Authentication")
    auth_choices = [
        ("Free tier (no login)", "auto-activates, access to free content"),
        ("Login with account", "email + password for premium content"),
    ]
    auth_idx = select_menu("Select authentication", auth_choices, back=False)
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
            ("Search",            "find by name"),
            ("Latest",            "browse newest movies & series"),
            ("By Genre",          "Action, Comedy, Horror, Anime..."),
            ("By Year",           "2026, 2025, 2024..."),
            ("By Country",        "Japan, South Korea, USA..."),
            ("By Actor/Director", "search by person"),
            ("Recommendations",   "similar to a title you like"),
            ("Live TV",           "1000+ channels by category"),
            ("Help",              "usage guide"),
            ("Exit",              ""),
        ]
        idx = select_menu("Select", menu, back=False)
        if idx is None or idx == 9:
            console.print("\n  [dim]Bye![/dim]\n")
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
        console.print("\n\n  [dim]Interrupted. Bye![/dim]\n")
        sys.exit(0)
