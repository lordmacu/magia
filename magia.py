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
import telegram_notifier as tg
from live_stream import LiveSession, LiveProxy

console = Console()

API_DELAY = 1.5
DOWNLOAD_DELAY = 0.5

# ─── i18n ───
LANG = "en"

STRINGS = {
    "en": {
        "subtitle": "IPTV Media Tool -- Search, Stream & Download",
        "auth": "Authentication",
        "free_tier": "Free tier (no login)",
        "free_hint": "auto-activates, access to free content",
        "login_account": "Login with account",
        "login_hint": "email + password for premium content",
        "select_auth": "Select authentication",
        "connecting": "Connecting to IPTV portal...",
        "connected_free": "Connected (free tier)",
        "cdn_auth": "Getting CDN authorization...",
        "cdn_ready": "CDN ready",
        "cdn_valid": "auth valid for {h:.1f} hours",
        "cdn_no_cf": "No Cloudflare CDN found (downloads may not work)",
        "main_menu": "Main Menu",
        "search": "Search",
        "search_hint": "find by name",
        "latest": "Latest",
        "latest_hint": "browse newest movies & series",
        "by_genre": "By Genre",
        "genre_hint": "Action, Comedy, Horror, Anime...",
        "by_year": "By Year",
        "year_hint": "2026, 2025, 2024...",
        "by_country": "By Country",
        "country_hint": "Japan, South Korea, USA...",
        "by_person": "By Actor/Director",
        "person_hint": "search by person",
        "recommendations": "Recommendations",
        "rec_hint": "similar to a title you like",
        "live_tv": "Live TV",
        "live_hint": "1000+ channels by category",
        "telegram": "Telegram",
        "telegram_hint": "download notifications",
        "help": "Help",
        "help_hint": "usage guide",
        "exit": "Exit",
        "select": "Select",
        "bye": "Bye!",
        "search_prompt": "Search",
        "searching": "Searching '{q}'...",
        "results_title": "Results for '{q}' ({n} total)",
        "no_results": "No results for '{q}'",
        "series": "Series",
        "movie": "Movie",
        "loading_eps": "Loading episodes...",
        "found_eps": "Found {n} episodes",
        "no_eps": "No episodes found",
        "dl_all": "Download ALL episodes",
        "dl_range": "Download a range",
        "dl_single": "Download a single episode",
        "browse_eps": "Browse episode list",
        "view_details": "View details",
        "view_link": "View details & stream URL",
        "what_to_do": "What do you want to do?",
        "from_ep": "From episode (1-{n})",
        "to_ep": "To episode ({s}-{n})",
        "ep_number": "Episode number (1-{n})",
        "downloading": "Downloading {name}: ep {s}-{e}",
        "output": "Output: {path}",
        "dl_complete": "Download Complete",
        "downloaded": "Downloaded",
        "skipped": "Skipped",
        "failed": "Failed",
        "total_size": "Total size",
        "location": "Location",
        "open_folder": "Open download folder?",
        "dl_movie": "Download",
        "dl_movie_hint": "download the movie file",
        "view_details_hint": "full info (cast, description, streams)",
        "view_link_hint": "stream URL without downloading",
        "getting_streams": "Getting streams...",
        "dl_this_movie": "Download this movie?",
        "overwrite": "Overwrite?",
        "already_exists": "Already exists: {name} ({size:.1f} MB)",
        "stream_url": "Stream URL",
        "copy_hint": "Copy this URL to play in VLC or any player",
        "stream_play": "Stream (open in player)",
        "stream_play_hint": "play directly in VLC/mpv",
        "opening_player": "Opening in {player}...",
        "no_player": "No player found",
        "installing_vlc": "Installing VLC...",
        "vlc_installed": "VLC installed",
        "vlc_install_fail": "Could not install VLC automatically. Install it manually: https://www.videolan.org",
        "select_stream": "Select stream quality",
        "select_ep_stream": "Which episode to stream? (1-{n})",
        "subs_loaded": "Subtitles loaded: {langs}",
        "subs_available": "Available subtitles",
        "no_subs": "No subtitles available",
        "email_user": "Email / username",
        "enc_password": "Password",
        "using_creds": "Using credentials from .env ({u})",
        "pwd_tip": "Enter your account password in plain text (it is MD5-hashed automatically).",
        "fallback_free": "Falling back to free tier...",
        "login_failed": "Login failed: {msg}",
        "logged_in": "Logged in",
        "save_creds": "Save these credentials for auto-login next time?",
        "creds_saved": "Credentials saved to .env",
        "switch_hint": "Auto-login is on. Run 'magia --switch' to change account, or 'magia --free' for free tier.",
        "relogin_menu": "Saved credentials didn't work. Opening the sign-in menu...",
        "logout": "Log out",
        "logout_hint": "forget the saved account (stops auto-login)",
        "logged_out": "Logged out. Saved credentials removed from .env.",
        "register": "Register",
        "register_hint": "create account: email + password",
        "recover_pwd": "Recover password",
        "recover_hint": "reset password via email code",
        "sending_code": "Sending verification code to {email}...",
        "code_sent": "Verification code sent. Check your email (and spam).",
        "code_send_fail": "Could not send code: {msg}",
        "verify_code": "Verification code (from your email)",
        "new_password": "New password",
        "register_fail": "Registration failed: {msg}",
        "registered": "Account registered and logged in",
        "reset_fail": "Password reset failed: {msg}",
        "pwd_reset_ok": "Password reset and logged in",
        "email_required": "Please enter an email / username to continue.",
        "code_required": "Please enter the verification code from your email (it can't be empty).",
        "pwd_required": "Please enter a password (it can't be empty).",
        "newpwd_required": "Please enter a new password (it can't be empty).",
        "check_email_hint": "Now open your inbox (and the spam folder), copy the code, and paste it below.",
        "validating_code": "Validating the code...",
        "code_ok": "Code validated.",
        "creating_account": "Creating your account...",
        "logging_in": "Signing in...",
        "resetting": "Resetting your password...",
        "activating": "Activating device (free account)...",
        "not_activated": "The device could not be activated (no userId). Check your connection / .env and try again.",
        "device_linked": "This device is linked to an account, so free tier no longer works on it. Provisioning a fresh anonymous device...",
        "provisioning": "Creating a new anonymous device...",
        "device_saved": "New anonymous device saved to .env.",
        "provision_failed": "Could not create a new device: {msg}",
        "email_in_use": "That email is already registered. Use 'Login' or 'Recover password' instead.",
        "one_email_note": "Note: each device can register only one email (provider rule). To register another, you need a fresh device SN.",
        "cancelled": "Cancelled -- nothing was changed.",
        "lang_prompt": "Language / Idioma",
    },
    "es": {
        "subtitle": "IPTV Media Tool -- Buscar, Transmitir y Descargar",
        "auth": "Autenticacion",
        "free_tier": "Modo gratuito (sin login)",
        "free_hint": "se activa solo, acceso a contenido free",
        "login_account": "Iniciar sesion",
        "login_hint": "email + contrasena para contenido premium",
        "select_auth": "Selecciona autenticacion",
        "connecting": "Conectando al portal IPTV...",
        "connected_free": "Conectado (modo gratuito)",
        "cdn_auth": "Obteniendo autorizacion CDN...",
        "cdn_ready": "CDN listo",
        "cdn_valid": "auth valido por {h:.1f} horas",
        "cdn_no_cf": "No se encontro CDN Cloudflare (las descargas pueden no funcionar)",
        "main_menu": "Menu Principal",
        "search": "Buscar",
        "search_hint": "buscar por nombre",
        "latest": "Recientes",
        "latest_hint": "peliculas y series mas nuevas",
        "by_genre": "Por Genero",
        "genre_hint": "Accion, Comedia, Horror, Anime...",
        "by_year": "Por Ano",
        "year_hint": "2026, 2025, 2024...",
        "by_country": "Por Pais",
        "country_hint": "Japon, Corea del Sur, USA...",
        "by_person": "Por Actor/Director",
        "person_hint": "buscar por persona",
        "recommendations": "Recomendaciones",
        "rec_hint": "similar a un titulo que te guste",
        "live_tv": "TV en Vivo",
        "live_hint": "1000+ canales por categoria",
        "telegram": "Telegram",
        "telegram_hint": "notificaciones de descarga",
        "help": "Ayuda",
        "help_hint": "guia de uso",
        "exit": "Salir",
        "select": "Selecciona",
        "bye": "Hasta luego!",
        "search_prompt": "Buscar",
        "searching": "Buscando '{q}'...",
        "results_title": "Resultados para '{q}' ({n} en total)",
        "no_results": "Sin resultados para '{q}'",
        "series": "Serie",
        "movie": "Pelicula",
        "loading_eps": "Cargando episodios...",
        "found_eps": "Encontrados {n} episodios",
        "no_eps": "No se encontraron episodios",
        "dl_all": "Descargar TODOS los episodios",
        "dl_range": "Descargar un rango",
        "dl_single": "Descargar un solo episodio",
        "browse_eps": "Ver lista de episodios",
        "view_details": "Ver detalles",
        "view_link": "Ver detalles y URL del stream",
        "what_to_do": "Que deseas hacer?",
        "from_ep": "Desde episodio (1-{n})",
        "to_ep": "Hasta episodio ({s}-{n})",
        "ep_number": "Numero de episodio (1-{n})",
        "downloading": "Descargando {name}: ep {s}-{e}",
        "output": "Destino: {path}",
        "dl_complete": "Descarga Completa",
        "downloaded": "Descargados",
        "skipped": "Omitidos",
        "failed": "Fallidos",
        "total_size": "Tamano total",
        "location": "Ubicacion",
        "open_folder": "Abrir carpeta de descargas?",
        "dl_movie": "Descargar",
        "dl_movie_hint": "descargar la pelicula",
        "view_details_hint": "info completa (cast, descripcion, streams)",
        "view_link_hint": "URL del stream sin descargar",
        "getting_streams": "Obteniendo streams...",
        "dl_this_movie": "Descargar esta pelicula?",
        "overwrite": "Sobrescribir?",
        "already_exists": "Ya existe: {name} ({size:.1f} MB)",
        "stream_url": "URL del Stream",
        "copy_hint": "Copia esta URL para reproducir en VLC u otro reproductor",
        "stream_play": "Reproducir (abrir en reproductor)",
        "stream_play_hint": "reproducir directo en VLC/mpv",
        "opening_player": "Abriendo en {player}...",
        "no_player": "No se encontro reproductor",
        "installing_vlc": "Instalando VLC...",
        "vlc_installed": "VLC instalado",
        "vlc_install_fail": "No se pudo instalar VLC automaticamente. Instalalo manualmente: https://www.videolan.org",
        "select_stream": "Selecciona calidad del stream",
        "select_ep_stream": "Que episodio reproducir? (1-{n})",
        "subs_loaded": "Subtitulos cargados: {langs}",
        "subs_available": "Subtitulos disponibles",
        "no_subs": "Sin subtitulos disponibles",
        "email_user": "Email / usuario",
        "enc_password": "Contrasena",
        "using_creds": "Usando credenciales del .env ({u})",
        "pwd_tip": "Escribe tu contrasena en texto plano (se hashea con MD5 automaticamente).",
        "fallback_free": "Cambiando a modo gratuito...",
        "login_failed": "Login fallido: {msg}",
        "logged_in": "Sesion iniciada",
        "save_creds": "Guardar estas credenciales para auto-login la proxima vez?",
        "creds_saved": "Credenciales guardadas en .env",
        "switch_hint": "Auto-login activo. Corre 'magia --switch' para cambiar de cuenta, o 'magia --free' para modo gratuito.",
        "relogin_menu": "Las credenciales guardadas no funcionaron. Abriendo el menu de sesion...",
        "logout": "Cerrar sesion",
        "logout_hint": "olvida la cuenta guardada (deja de auto-loguear)",
        "logged_out": "Sesion cerrada. Credenciales removidas del .env.",
        "register": "Registrarse",
        "register_hint": "crear cuenta: email + contrasena",
        "recover_pwd": "Recuperar contrasena",
        "recover_hint": "resetear contrasena por codigo al email",
        "sending_code": "Enviando codigo de verificacion a {email}...",
        "code_sent": "Codigo enviado. Revisa tu email (y spam).",
        "code_send_fail": "No se pudo enviar el codigo: {msg}",
        "verify_code": "Codigo de verificacion (del email)",
        "new_password": "Nueva contrasena",
        "register_fail": "Registro fallido: {msg}",
        "registered": "Cuenta registrada y sesion iniciada",
        "reset_fail": "Reset de contrasena fallido: {msg}",
        "pwd_reset_ok": "Contrasena reseteada y sesion iniciada",
        "email_required": "Escribe un email / usuario para continuar.",
        "code_required": "Escribe el codigo de verificacion que llego a tu email (no puede quedar vacio).",
        "pwd_required": "Escribe una contrasena (no puede quedar vacia).",
        "newpwd_required": "Escribe una contrasena nueva (no puede quedar vacia).",
        "check_email_hint": "Ahora abre tu correo (y la carpeta de spam), copia el codigo y pegalo abajo.",
        "validating_code": "Validando el codigo...",
        "code_ok": "Codigo validado.",
        "creating_account": "Creando tu cuenta...",
        "logging_in": "Iniciando sesion...",
        "resetting": "Reseteando tu contrasena...",
        "activating": "Activando dispositivo (cuenta gratuita)...",
        "not_activated": "No se pudo activar el dispositivo (sin userId). Revisa tu conexion / .env e intenta de nuevo.",
        "device_linked": "Este dispositivo esta atado a una cuenta, asi que el modo gratuito ya no funciona en el. Creando un device anonimo nuevo...",
        "provisioning": "Creando un device anonimo nuevo...",
        "device_saved": "Device anonimo nuevo guardado en .env.",
        "provision_failed": "No se pudo crear un device nuevo: {msg}",
        "email_in_use": "Ese email ya esta registrado. Usa 'Iniciar sesion' o 'Recuperar contrasena'.",
        "one_email_note": "Nota: cada dispositivo solo puede registrar un email (regla del proveedor). Para otro, necesitas un SN nuevo.",
        "cancelled": "Cancelado -- no se cambio nada.",
        "lang_prompt": "Language / Idioma",
    },
}


def t(key, **kwargs):
    s = STRINGS.get(LANG, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    if kwargs:
        return s.format(**kwargs)
    return s

def _is_frozen():
    return getattr(sys, 'frozen', False)

def _app_dir():
    if _is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent

def _env_dir():
    if (Path.cwd() / ".env").exists():
        return Path.cwd()
    home_magia = Path.home() / ".magia"
    if (home_magia / ".env").exists():
        return home_magia
    if _is_frozen():
        home_magia.mkdir(parents=True, exist_ok=True)
        return home_magia
    return _app_dir()

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
DISCLAIMER_EN = (
    "This tool does not own, host, or distribute any content or servers.\n"
    "All content belongs to and is served by Magis TV / Xuper.\n"
    "Built via reverse engineering of the APK for personal/educational use only."
)
DISCLAIMER_ES = (
    "Esta herramienta no posee, aloja ni distribuye contenido ni servidores.\n"
    "Todo el contenido pertenece y es servido por Magis TV / Xuper.\n"
    "Construido mediante ingenieria inversa del APK solo para uso personal/educativo."
)

def banner():
    console.print(BANNER)
    console.print("  [dim]IPTV Media Tool -- Search, Stream & Download[/dim]\n")
    disc = DISCLAIMER_ES if LANG == "es" else DISCLAIMER_EN
    console.print(Panel(disc, border_style="yellow", padding=(0, 2), title="Disclaimer"))

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


def ask_secret(prompt):
    """Prompt de password OCULTO (no muestra lo que se escribe)."""
    try:
        return inquirer.secret(message=prompt).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception:
        # fallback si el terminal no soporta secret
        import getpass
        try:
            return getpass.getpass(prompt + ": ")
        except (KeyboardInterrupt, EOFError):
            return None


def confirm(prompt, default=True):
    try:
        return inquirer.confirm(message=prompt, default=default).execute()
    except (KeyboardInterrupt, EOFError):
        return None


# Color por opcion en los menus. InquirerPy 0.3.4 no lo soporta nativo (cada opcion se
# dibuja con una sola clase de estilo), asi que parcheamos el list-control para pintar el
# nombre segun _MENU_STYLE (mapa nombre_mostrado -> estilo prompt_toolkit, ej "fg:ansigreen").
_MENU_STYLE = {}

def _install_menu_color_patch():
    try:
        from InquirerPy.prompts.list import InquirerPyListControl
    except Exception:
        return
    if getattr(InquirerPyListControl, "_magia_color_patched", False):
        return
    _orig_normal = InquirerPyListControl._get_normal_text
    def _normal(self, choice):
        frags = _orig_normal(self, choice)
        style = _MENU_STYLE.get(choice.get("name"))
        if not style:
            return frags
        # recolorea solo el fragmento del nombre (clase vacia), deja marker/espacios intactos
        return [(style, txt) if (cls == "" and txt == choice.get("name")) else (cls, txt)
                for (cls, txt) in frags]
    InquirerPyListControl._get_normal_text = _normal
    InquirerPyListControl._magia_color_patched = True

_install_menu_color_patch()


def select_menu(prompt, choices, back=True):
    """choices: lista de (label, hint) o (label, hint, style).  `style` es un estilo
    prompt_toolkit (ej 'fg:ansigreen') que colorea esa opcion cuando NO esta resaltada."""
    items = []
    _MENU_STYLE.clear()
    for choice in choices:
        label, hint = choice[0], choice[1]
        style = choice[2] if len(choice) > 2 else None
        name = f"{label}  — {hint}" if hint else label
        items.append({"name": name, "value": label})
        if style:
            _MENU_STYLE[name] = style
    if back:
        items.append(Separator())
        items.append({"name": "<- Back", "value": "__back__"})
    try:
        result = inquirer.select(
            message=prompt,
            choices=items,
            pointer=">",
        ).execute()
        if result == "__back__":
            return None
        for i, choice in enumerate(choices):
            if choice[0] == result:
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
                "audio": m.get("audioInfo", ""),
            })
    if not streams:
        return None, "No streams"
    streams.sort(key=lambda s: (0 if s["encode_format"] == "h264" else 1))

    subtitles = []
    for sub in ep_data.get("subtitleList", []):
        files = sub.get("file", [])
        if files and files[0].get("url"):
            subtitles.append({
                "lang": sub.get("language", "?"),
                "url": files[0]["url"],
                "type": files[0].get("fileType", "srt"),
            })

    return streams, None, subtitles


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
        choices.append({"name": "<- Back", "value": "__back__"})

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
    query = ask(t("search_prompt"))
    if not query:
        return None
    info(t("searching", q=query))
    time.sleep(API_DELAY)
    sr = client.search(query, size=30)
    items = []
    for grp in sr.get("searchItemList", []):
        items.extend(grp.get("itemList", []))
    if not items:
        warn(t("no_results", q=query))
        return None
    total = sr.get("totalSize", len(items))
    section(t("results_title", q=query, n=total))
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
        choices.append({"name": "<- Back", "value": "__back__"})

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
        _handle_live_channel(client, channel_item.get("channelCode", ""),
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

    feat_idx = idx
    if feat_idx < len(FEATURED_CATS):
        col_id = FEATURED_CATS[feat_idx][0]
        cat_name = FEATURED_CATS[feat_idx][1]
    elif idx == len(cat_choices) - 1:
        _live_search(client)
        return
    else:
        country_idx = feat_idx - len(FEATURED_CATS)
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
        choices.append({"name": "<- Back", "value": "__back__"})

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
                _handle_live_channel(client, ch["channelCode"], ch.get("name", ""))


def _handle_live_channel(client, channel_code, channel_name):
    choices = [
        ("▶ Stream", "open in VLC/mpv", "fg:ansigreen"),   # reproductor -> verde
        ("≡ View details", "playCode, license, CDN"),
    ]
    idx = select_menu(f"{channel_name}", choices)
    if idx is None:
        return
    if idx == 0:
        stream_live(client, channel_code, channel_name)
    else:
        show_live_url(client, channel_code, channel_name)


# ─── Live TV: streaming independiente (sin app ni emulador) vía sign_o3 ───
_ACTIVE_LIVE_PROXIES = []  # mantiene vivos los proxies mientras dure la sesión del CLI


def get_live_cdn_auth(client, channel_code):
    """Devuelve (host, auth_prefix) para TV en vivo desde get_slb(live).
    auth_prefix = el Content-Auth SIN &start_moment/&sign2 (los agrega live_stream por request)."""
    slb = client.get_slb(type_="merge", live_codes=[channel_code or "masnew_live"])
    if isinstance(slb, dict) and "_error" not in slb:
        for cdn in slb.get("cdn_list", []):
            for u in cdn.get("url_list", []):
                url = u.get("url", "")
                if "sign2_method=sign_o3" in url and "&token=" in url:
                    mh = re.search(r"[?&]host=([^&]+)", url)
                    host = mh.group(1) if mh else cdn.get("main_addr", "").split("//")[-1].rstrip("/")
                    return host, url
    return None, None


def stream_live(client, channel_code, channel_name):
    """Reproduce TV en vivo 100% Python (sin app ni emulador): resuelve el CDN Cloudflare
    (sign_type=cfl) via get_slb — igual que las películas — y levanta un proxy HLS local que
    re-firma cada segmento .ts con sign_o3 (live_cfl.py). Ver MAGIA_RUNBOOK.md."""
    import live_cfl
    player = _ensure_player()
    if not player:
        return
    if not channel_code:
        error("No hay canal seleccionado.")
        return

    info(f"Preparando: {channel_name}...")
    time.sleep(API_DELAY)

    # Resolver el CDN cfl (host + Content-Auth + Content-License + token) y levantar el proxy.
    try:
        host, cfl_url, content_license, token = live_cfl.resolve_live_cfl(client, channel_code)
    except Exception as e:
        error(f"No se pudo resolver el canal en vivo: {e}")
        return

    httpd, port = live_cfl.start_proxy(host, cfl_url, content_license, token, channel_code)
    _ACTIVE_LIVE_PROXIES.append(httpd)
    url = f"http://127.0.0.1:{port}/play.m3u8"

    success(f"Streaming: {channel_name}")
    info(f"Proxy local (cfl + sign_o3) en 127.0.0.1:{port}")

    # Mismo abridor que películas/capítulos: en Mac prefiere VLC (open -a VLC).
    # El proxy ya maneja Content-Auth/Content-License + sign_o3, así que el player sólo abre la URL.
    _open_in_player(player, url, "", "")


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
    table.add_row("Quality", addr.get("quality", "?"))
    table.add_row("Tag", addr.get("tag", "?"))
    console.print(table)

    console.print(f"\n  [bold]License:[/bold]\n  [dim]{license_str}[/dim]")

    seen = set()
    qualities = []
    for a in addrs:
        pc = a.get("playCode", "")
        if pc in seen:
            continue
        seen.add(pc)
        q = a.get("quality", "")
        if not q:
            q = "HD" if "720" in pc else "SD" if "480" in pc else "FHD" if "fhd" in pc.lower() else "?"
        qualities.append((pc, q, a.get("tag", "?")))

    if len(qualities) > 1:
        console.print("\n  [bold]Available streams:[/bold]")
        for pc, q, tag in qualities:
            console.print(f"    [cyan]-[/cyan] {pc}  [dim]({q}, {tag})[/dim]")


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

    section(f"{t('series')}: {name}")

    tags = item.get("tags", "")
    score = item.get("score", "")
    year = (item.get("releaseTime") or "")[:4]
    if any([tags, score, year]):
        parts = []
        if year: parts.append(year)
        if score: parts.append(f"*{score}")
        if tags: parts.append(tags[:50])
        console.print(f"  [dim]{' | '.join(parts)}[/dim]\n")

    info(t("loading_eps"))
    time.sleep(API_DELAY)
    episodes = client.episodes(content_id)
    if not episodes:
        error(t("no_eps"))
        return
    success(t("found_eps", n=len(episodes)))

    safe_name = re.sub(r'[^\w\s\-]', '', name).strip().replace(' ', '_')
    series_dir = out_dir / safe_name

    choices = [
        (f"↓ {t('dl_all')}", f"{len(episodes)} eps -> {safe_name}/"),
        (f"↓ {t('dl_range')}", "e.g. episodes 1-10"),
        (f"↓ {t('dl_single')}", ""),
        (f"▸ {t('browse_eps')}", ""),
        (f"▶ {t('stream_play')}", t("stream_play_hint"), "fg:ansigreen"),   # reproductor -> verde
        (f"≡ {t('view_details')}", ""),
        (f"↗ {t('view_link')}", t("view_link_hint")),
    ]
    idx = select_menu(t("what_to_do"), choices)
    if idx is None:
        return

    if idx == 4:
        stream_episode(client, item, episodes, cdn_base, cf_auth)
        return

    if idx == 5:
        show_detail(client, item)
        return

    if idx == 6:
        show_episode_links(client, item, episodes, cdn_base, cf_auth)
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
        val = ask(t("from_ep", n=len(episodes)), "1")
        if val is None: return
        try: start_ep = max(1, min(int(val), len(episodes)))
        except ValueError: start_ep = 1
        val = ask(t("to_ep", s=start_ep, n=len(episodes)), str(len(episodes)))
        if val is None: return
        try: end_ep = max(start_ep, min(int(val), len(episodes)))
        except ValueError: end_ep = len(episodes)
    elif idx == 2:
        val = ask(t("ep_number", n=len(episodes)))
        if val is None: return
        try: start_ep = max(1, min(int(val), len(episodes)))
        except ValueError: start_ep = 1
        end_ep = start_ep
    else:
        start_ep, end_ep = 1, len(episodes)

    series_dir.mkdir(parents=True, exist_ok=True)

    section(t("downloading", name=name, s=start_ep, e=end_ep))
    info(t("output", path=str(series_dir)))
    console.print()

    total_to_dl = end_ep - start_ep + 1
    tg.notify_batch_start(name, total_to_dl, f"{start_ep}-{end_ep}")

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
        streams, err, _subs = resolve_streams(client, ep["contentId"], series_content_id=content_id)
        if err:
            cur_base, cur_auth = refresh_auth_if_needed(client, err, cur_base, cur_auth)
            auth_counter = 0
            time.sleep(API_DELAY)
            streams, err, _subs = resolve_streams(client, ep["contentId"], series_content_id=content_id)
            if err:
                error(f"Failed: {err}")
                tg.notify_download_fail(name, episode=ep_num, reason=str(err))
                stats["fail"] += 1
                continue

        s = streams[0]
        out_file = series_dir / f"ep{ep_num:03d}.{s['video_format']}"

        size, dl_err = download_file(cur_base, s["media_code"], cur_auth, s["license"],
                                     out_file, video_format=s["video_format"])
        if dl_err and "401" in str(dl_err):
            cur_base, cur_auth = get_cf_vod_auth(client)
            time.sleep(API_DELAY)
            streams, _, _subs = resolve_streams(client, ep["contentId"], series_content_id=content_id)
            if streams:
                s = streams[0]
                time.sleep(API_DELAY)
                size, dl_err = download_file(cur_base, s["media_code"], cur_auth, s["license"],
                                             out_file, video_format=s["video_format"])
        if dl_err:
            error(f"FAILED: {dl_err}")
            tg.notify_download_fail(name, episode=ep_num, reason=str(dl_err))
            stats["fail"] += 1
            continue

        success(f"{size / (1024*1024):.1f} MB")
        if out_file.suffix == ".ts":
            convert_ts_to_mp4(out_file)
        tg.notify_download_ok(name, episode=ep_num, size_mb=size / (1024*1024),
                              path=str(out_file.name))
        stats["ok"] += 1
        time.sleep(DOWNLOAD_DELAY)

    section(t("dl_complete"))
    total_size = sum(f.stat().st_size for f in series_dir.iterdir()
                     if f.suffix in (".mp4", ".ts"))

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary.add_column("Stat", style="bold")
    summary.add_column("Value")
    summary.add_row(f"[green]{t('downloaded')}[/green]", str(stats["ok"]))
    summary.add_row(f"[yellow]{t('skipped')}[/yellow]", str(stats["skip"]))
    summary.add_row(f"[red]{t('failed')}[/red]", str(stats["fail"]))
    summary.add_row(f"[blue]{t('total_size')}[/blue]", f"{total_size / (1024**3):.2f} GB")
    summary.add_row(f"[dim]{t('location')}[/dim]", str(series_dir))
    console.print(summary)

    tg.notify_batch_complete(name, ok=stats["ok"], failed=stats["fail"],
                             skipped=stats["skip"],
                             total_size=f"{total_size / (1024**3):.2f} GB")

    if confirm(t("open_folder"), default=True):
        open_folder(series_dir)


# ─── Movie handler ───
def handle_movie(client, item, cdn_base, cf_auth, out_dir):
    content_id = item["contentId"]
    name = item.get("name", "Movie")

    section(f"{t('movie')}: {name}")

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
        (f"↓ {t('dl_movie')}", t("dl_movie_hint")),
        (f"▶ {t('stream_play')}", t("stream_play_hint"), "fg:ansigreen"),   # reproductor -> verde
        (f"≡ {t('view_details')}", t("view_details_hint")),
        (f"↗ {t('view_link')}", t("view_link_hint")),
    ]
    idx = select_menu(t("what_to_do"), choices)
    if idx is None:
        return

    if idx == 1:
        stream_movie(client, item, cdn_base, cf_auth)
        return

    if idx == 2:
        show_detail(client, item)
        if not confirm(t("dl_this_movie"), default=False):
            return

    if idx == 3:
        show_movie_link(client, item, cdn_base, cf_auth)
        return

    info(t("getting_streams"))
    time.sleep(API_DELAY)

    streams, err, _subs = resolve_streams(client, content_id)
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
        warn(t("already_exists", name=out_file.name, size=out_file.stat().st_size / 1e6))
        if not confirm(t("overwrite"), default=False):
            return

    section(f"{t('downloading', name=name, s='', e='')}")
    info(f"Format: {s['encode_format']}/{s['video_format']} {s['quality']}")
    info(t("output", path=str(out_file)))
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
        tg.notify_download_fail(name, reason=str(dl_err))
        return
    console.print()
    if out_file.suffix == ".ts":
        out_file = convert_ts_to_mp4(out_file)
    success(f"{t('downloaded')}: {out_file.name} ({size / (1024*1024):.1f} MB)")
    tg.notify_download_ok(name, size_mb=size / (1024*1024), path=str(out_file.name))
    if confirm(t("open_folder"), default=True):
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
        "[bold]Login:[/bold]     email + password (for account features)\n"
        "[bold]Auto-login:[/bold] once saved, 'magia' logs you in automatically\n"
        "  [dim]magia --switch[/dim]      change account / register / recover / log out\n"
        "  [dim]magia --free[/dim]        force free tier for one run\n"
        "  [dim]magia --new-device[/dim]  provision a fresh anonymous device (free tier)\n\n"
        "Press [bold]Ctrl+C[/bold] to exit at any time\n"
        "Downloaded episodes are auto-skipped on re-run\n"
        "CDN auth refreshes every 30 episodes automatically",
        title="Tips",
        border_style="dim",
        padding=(0, 2),
    ))


# ─── Telegram notifications ───
def configure_telegram():
    section("Telegram Notifications")

    env_path = _env_dir() / ".env"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("TELEGRAM_ENABLED", "")
    is_on = enabled.lower() in ("1", "true", "yes", "si")

    if token and chat_id:
        status = "[green]Connected[/green]" if is_on else "[yellow]Disabled[/yellow]"
        console.print(f"  Status: {status}")
        console.print(f"  Bot token: [dim]{token[:10]}...{token[-4:]}[/dim]")
        console.print(f"  Chat ID: [dim]{chat_id}[/dim]")
        console.print()

        choices = [
            ("Toggle on/off", "enable or disable notifications"),
            ("Test connection", "send a test message to Telegram"),
            ("Reconfigure", "change bot token or chat ID"),
            ("Remove config", "delete Telegram settings from .env"),
        ]
        idx = select_menu("Telegram options", choices)
        if idx is None:
            return

        if idx == 0:
            new_val = "0" if is_on else "1"
            os.environ["TELEGRAM_ENABLED"] = new_val
            _update_env_var(env_path, "TELEGRAM_ENABLED", new_val)
            if new_val == "1":
                success("Telegram notifications enabled")
            else:
                info("Telegram notifications disabled")
            return

        if idx == 1:
            info("Sending test message...")
            ok, msg = tg.test_connection()
            if ok:
                success("Test message sent! Check your Telegram.")
            else:
                error(f"Failed: {msg}")
            return

        if idx == 3:
            if confirm("Remove Telegram configuration?", default=False):
                for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ENABLED"):
                    os.environ.pop(var, None)
                    _update_env_var(env_path, var, "")
                success("Telegram configuration removed")
            return

    console.print(Panel(
        "[bold]Link your Telegram to receive download notifications.[/bold]\n\n"
        "1. Open Telegram and search for [cyan]@BotFather[/cyan]\n"
        "2. Send [cyan]/newbot[/cyan] and follow the steps to create a bot\n"
        "3. Copy the bot [bold]token[/bold] (e.g. 123456:ABC-DEF...)\n"
        "4. Start a chat with your bot and send any message\n"
        "5. Get your chat ID from [cyan]@userinfobot[/cyan] or the API",
        title="How to set up",
        border_style="cyan",
        padding=(1, 2),
    ))

    new_token = ask("Bot token (from @BotFather)", token)
    if not new_token:
        warn("Cancelled")
        return

    new_chat_id = ask("Chat ID (numeric)", chat_id)
    if not new_chat_id:
        warn("Cancelled")
        return

    os.environ["TELEGRAM_BOT_TOKEN"] = new_token
    os.environ["TELEGRAM_CHAT_ID"] = new_chat_id
    os.environ["TELEGRAM_ENABLED"] = "1"

    _update_env_var(env_path, "TELEGRAM_BOT_TOKEN", new_token)
    _update_env_var(env_path, "TELEGRAM_CHAT_ID", new_chat_id)
    _update_env_var(env_path, "TELEGRAM_ENABLED", "1")

    info("Testing connection...")
    ok, msg = tg.test_connection()
    if ok:
        success("Telegram linked! You'll receive notifications for downloads.")
    else:
        error(f"Connection failed: {msg}")
        warn("Check your token and chat ID, then try again.")


def _update_env_var(env_path, var, value):
    if not env_path.exists():
        env_path.write_text(f"\n# Telegram\n{var}={value}\n")
        return
    content = env_path.read_text()
    import re as _re
    if _re.search(rf'^{var}=', content, _re.MULTILINE):
        # OJO: `value` va como funcion de reemplazo, NO como string, para que re.sub
        # no interprete secuencias tipo \1 o \g<..> (passwords con backslash rompian esto).
        content = _re.sub(rf'^{var}=.*$', lambda _m: f'{var}={value}', content, flags=_re.MULTILINE)
    else:
        if "# Telegram" not in content:
            content += "\n# Telegram notifications\n"
        content += f"{var}={value}\n"
    env_path.write_text(content)


# ─── View stream URL without downloading ───
def _find_player():
    plat = sys.platform
    if plat == "darwin":
        for app in ["VLC", "IINA", "mpv"]:
            if Path(f"/Applications/{app}.app").exists():
                return app.lower()
        if shutil.which("mpv"):
            return "mpv"
    else:
        for cmd in ["vlc", "mpv", "celluloid"]:
            if shutil.which(cmd):
                return cmd
    return None


def _install_vlc():
    plat = sys.platform
    try:
        if plat == "darwin":
            if shutil.which("brew"):
                info(t("installing_vlc"))
                subprocess.run(["brew", "install", "--cask", "vlc"], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                success(t("vlc_installed"))
                return True
        elif plat == "linux":
            for mgr in [["sudo", "apt", "install", "-y", "vlc"],
                         ["sudo", "dnf", "install", "-y", "vlc"],
                         ["sudo", "pacman", "-S", "--noconfirm", "vlc"]]:
                if shutil.which(mgr[1]):
                    info(t("installing_vlc"))
                    subprocess.run(mgr, check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    success(t("vlc_installed"))
                    return True
        elif plat == "win32":
            if shutil.which("winget"):
                info(t("installing_vlc"))
                subprocess.run(["winget", "install", "VideoLAN.VLC",
                                "--accept-source-agreements", "--accept-package-agreements"],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                success(t("vlc_installed"))
                return True
            elif shutil.which("choco"):
                info(t("installing_vlc"))
                subprocess.run(["choco", "install", "vlc", "-y"],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                success(t("vlc_installed"))
                return True
    except subprocess.CalledProcessError:
        pass
    return False


def _ensure_player():
    player = _find_player()
    if player:
        return player
    if _install_vlc():
        return _find_player() or "vlc"
    error(t("vlc_install_fail"))
    return None


def _open_in_player(player, url, content_auth, content_license, subtitles=None):
    headers_str = (f"Content-Auth: {content_auth}\r\n"
                   f"Content-License: {content_license}\r\n"
                   f"User-Agent: Ranger/4.9.4-17294ac0\r\n"
                   f"App: {os.environ.get('IPTV_APP_ID', '')}\r\n"
                   f"App-Version: {os.environ.get('IPTV_APK_VERSION', '')}")

    sub_args = []
    if subtitles:
        for i, sub in enumerate(subtitles):
            sub_url = sub["url"]
            if player == "mpv":
                sub_args.extend([f"--sub-file={sub_url}"])
            elif player == "iina":
                sub_args.extend([f"--mpv-sub-file={sub_url}"])
            elif player == "vlc":
                if i == 0:
                    sub_args.extend([f"--sub-file={sub_url}"])

    plat = sys.platform
    if player == "mpv":
        cmd = ["mpv", f"--http-header-fields={headers_str}", url] + sub_args
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif player == "iina" and plat == "darwin":
        cmd = ["open", "-a", "IINA", url, "--args",
               f"--mpv-http-header-fields={headers_str}"] + sub_args
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif player == "vlc" and plat == "darwin":
        cmd = ["open", "-a", "VLC", url, "--args",
               f"--http-user-agent=Ranger/4.9.4-17294ac0"] + sub_args
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif player == "vlc":
        cmd = ["vlc", url, f"--http-user-agent=Ranger/4.9.4-17294ac0"] + sub_args
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen([player, url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info(t("opening_player", player=player.upper()))
    if subtitles:
        langs = ", ".join(s["lang"] for s in subtitles)
        info(t("subs_loaded", langs=langs))


def stream_movie(client, item, cdn_base, cf_auth):
    content_id = item["contentId"]
    name = item.get("name", "Movie")

    player = _ensure_player()
    if not player:
        return

    info(t("getting_streams"))
    time.sleep(API_DELAY)
    streams, err, subtitles = resolve_streams(client, content_id)
    if err:
        error(f"Failed: {err}")
        return

    if len(streams) > 1:
        stream_choices = []
        for s in streams:
            label = f"{s['encode_format']}/{s['video_format']}  {s['quality']}"
            if s.get("audio"):
                label += f" -- audio: {s['audio']}"
            stream_choices.append((label, ""))
        stream_idx = select_menu(t("select_stream"), stream_choices, back=False)
        if stream_idx is None:
            stream_idx = 0
    else:
        stream_idx = 0
        if streams[0].get("audio"):
            info(f"Audio: {streams[0]['audio']}")

    s = streams[stream_idx]
    ext = "ts" if s["video_format"] == "ts" else "mp4"
    url = f"{cdn_base}/vod/{s['media_code']}_media.{ext}"
    _open_in_player(player, url, cf_auth, s["license"], subtitles=subtitles)


def stream_episode(client, item, episodes, cdn_base, cf_auth):
    content_id = item["contentId"]

    val = ask(t("select_ep_stream", n=len(episodes)))
    if not val:
        return
    try:
        ep_num = max(1, min(int(val), len(episodes)))
    except ValueError:
        ep_num = 1

    ep = None
    for i, e in enumerate(episodes):
        n = int(e.get("seriesNumber") or (i + 1))
        if n == ep_num:
            ep = e
            break
    if not ep:
        error(f"Episode {ep_num} not found")
        return

    player = _ensure_player()
    if not player:
        return

    info(t("getting_streams"))
    time.sleep(API_DELAY)
    streams, err, subtitles = resolve_streams(client, ep["contentId"], series_content_id=content_id)
    if err:
        error(f"Failed: {err}")
        return

    if len(streams) > 1:
        stream_choices = []
        for s in streams:
            label = f"{s['encode_format']}/{s['video_format']}  {s['quality']}"
            if s.get("audio"):
                label += f" -- audio: {s['audio']}"
            stream_choices.append((label, ""))
        stream_idx = select_menu(t("select_stream"), stream_choices, back=False)
        if stream_idx is None:
            stream_idx = 0
    else:
        stream_idx = 0
        if streams[0].get("audio"):
            info(f"Audio: {streams[0]['audio']}")

    s = streams[stream_idx]
    ext = "ts" if s["video_format"] == "ts" else "mp4"
    url = f"{cdn_base}/vod/{s['media_code']}_media.{ext}"
    ep_name = ep.get("name", f"ep {ep_num}")
    section(f"{item.get('name', 'Series')} - {ep_name}")
    _open_in_player(player, url, cf_auth, s["license"], subtitles=subtitles)


def show_episode_links(client, item, episodes, cdn_base, cf_auth):
    content_id = item["contentId"]
    name = item.get("name", "Series")

    val = ask(t("ep_number", n=len(episodes)))
    if not val:
        return
    try:
        ep_num = max(1, min(int(val), len(episodes)))
    except ValueError:
        ep_num = 1

    ep = None
    for i, e in enumerate(episodes):
        n = int(e.get("seriesNumber") or (i + 1))
        if n == ep_num:
            ep = e
            break
    if not ep:
        error(f"Episode {ep_num} not found")
        return

    section(f"{name} - ep {ep_num}")

    ep_name = ep.get("name", "")
    desc = ep.get("description", "")
    quality = ep.get("quality", "")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_row("Episode", str(ep_num))
    if ep_name: table.add_row("Title", ep_name)
    if quality: table.add_row("Quality", quality)
    console.print(table)

    if desc:
        console.print(Panel(desc[:300], title="Synopsis", border_style="dim", padding=(0, 1)))

    info(t("getting_streams"))
    time.sleep(API_DELAY)
    streams, err, subtitles = resolve_streams(client, ep["contentId"], series_content_id=content_id)
    if err:
        error(f"Failed: {err}")
        return

    for s in streams:
        ext = "ts" if s["video_format"] == "ts" else "mp4"
        url = f"{cdn_base}/vod/{s['media_code']}_media.{ext}"
        audio = f"\nAudio: [yellow]{s['audio']}[/yellow]" if s.get("audio") else ""
        console.print()
        console.print(Panel(
            f"[bold]{s['encode_format']}/{s['video_format']} {s['quality']}[/bold]{audio}\n\n"
            f"[cyan]{url}[/cyan]\n\n"
            f"Content-Auth: [dim]{cf_auth[:40]}...[/dim]\n"
            f"Content-License: [dim]{s['license'][:40]}...[/dim]",
            title=t("stream_url"),
            border_style="green",
            padding=(1, 2),
        ))
    if subtitles:
        sub_lines = "\n".join(f"  [yellow]{s['lang']}[/yellow]: [cyan]{s['url']}[/cyan]" for s in subtitles)
        console.print(Panel(sub_lines, title=t("subs_available"), border_style="yellow", padding=(0, 2)))
    console.print(f"\n  [dim]{t('copy_hint')}[/dim]\n")


def show_movie_link(client, item, cdn_base, cf_auth):
    content_id = item["contentId"]
    name = item.get("name", "Movie")

    show_detail(client, item)

    info(t("getting_streams"))
    time.sleep(API_DELAY)
    streams, err, subtitles = resolve_streams(client, content_id)
    if err:
        error(f"Failed: {err}")
        return

    for s in streams:
        ext = "ts" if s["video_format"] == "ts" else "mp4"
        url = f"{cdn_base}/vod/{s['media_code']}_media.{ext}"
        audio = f"\nAudio: [yellow]{s['audio']}[/yellow]" if s.get("audio") else ""
        console.print()
        console.print(Panel(
            f"[bold]{s['encode_format']}/{s['video_format']} {s['quality']}[/bold]{audio}\n\n"
            f"[cyan]{url}[/cyan]\n\n"
            f"Content-Auth: [dim]{cf_auth[:40]}...[/dim]\n"
            f"Content-License: [dim]{s['license'][:40]}...[/dim]",
            title=t("stream_url"),
            border_style="green",
            padding=(1, 2),
        ))
    if subtitles:
        sub_lines = "\n".join(f"  [yellow]{s['lang']}[/yellow]: [cyan]{s['url']}[/cyan]" for s in subtitles)
        console.print(Panel(sub_lines, title=t("subs_available"), border_style="yellow", padding=(0, 2)))
    console.print(f"\n  [dim]{t('copy_hint')}[/dim]\n")


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
    ("IPTV_DEVICE_SN",       "Device SN (serial number hash)"),
]

OPTIONAL_VARS = [
    ("IPTV_APK_VERSION",     "APK Version (leave empty for default)"),
    ("IPTV_DEVICE_DRM_ID",   "Device DRM ID (leave empty to skip)"),
    ("IPTV_DEVICE_TOKEN",    "Device Token (leave empty to skip)"),
    ("IPTV_DEVICE_RESERVE1", "Device Reserve1 (leave empty to skip)"),
    ("IPTV_USERNAME",        "Login email (leave empty to skip)"),
    ("IPTV_PASSWORD",        "Login password (plain text, hashed automatically; leave empty to skip)"),
    ("IPTV_DOWNLOAD_DIR",    "Download directory"),
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
        if var == "IPTV_PASSWORD":
            # oculto; se guarda en TEXTO PLANO (login() lo hashea con MD5 al enviarlo).
            val = ask_secret(label)
        else:
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
        "# Device fingerprint (only SN is required)",
        f"IPTV_DEVICE_SN={values.get('IPTV_DEVICE_SN', '')}",
        "",
        "# APK identity",
        f"IPTV_APP_ID={values.get('IPTV_APP_ID', '')}",
        "",
        "# Optional device/APK fields (server accepts empty)",
        f"IPTV_APK_VERSION={values.get('IPTV_APK_VERSION', '')}",
        f"IPTV_DEVICE_DRM_ID={values.get('IPTV_DEVICE_DRM_ID', '')}",
        f"IPTV_DEVICE_TOKEN={values.get('IPTV_DEVICE_TOKEN', '')}",
        f"IPTV_DEVICE_RESERVE1={values.get('IPTV_DEVICE_RESERVE1', '')}",
        "",
        "# Login credentials (optional; password in PLAIN text, se hashea con MD5 al loguear)",
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


# ─── Auth: registro / recuperar contraseña ───
def _is_err(r):
    """True si la respuesta del cliente es un error: returnCode != 0 (`_error`) o
    fallo de red/parseo (`_exception`). Sin esto, una caida de red pasaba como exito."""
    return isinstance(r, dict) and ("_error" in r or "_exception" in r)


def _err_msg(r):
    """Mejor mensaje de error disponible en una respuesta del cliente."""
    if not isinstance(r, dict):
        return str(r)
    return r.get("_msg") or r.get("_error") or r.get("_exception") or ""


def _clear_saved_creds():
    """Borra IPTV_USERNAME/IPTV_PASSWORD del .env y del entorno (logout).
    _load_dotenv ignora valores vacios, asi que quedan efectivamente sin guardar."""
    env_path = _env_dir() / ".env"
    if env_path.exists():
        _update_env_var(env_path, "IPTV_USERNAME", "")
        _update_env_var(env_path, "IPTV_PASSWORD", "")
    os.environ.pop("IPTV_USERNAME", None)
    os.environ.pop("IPTV_PASSWORD", None)


def _maybe_save_creds(username, password):
    """Ofrece guardar credenciales en .env para auto-login la proxima vez."""
    if os.environ.get("IPTV_USERNAME") and os.environ.get("IPTV_PASSWORD"):
        return
    if confirm(t("save_creds"), default=True):
        env_path = _env_dir() / ".env"
        _update_env_var(env_path, "IPTV_USERNAME", username)
        _update_env_var(env_path, "IPTV_PASSWORD", password)
        os.environ["IPTV_USERNAME"] = username
        os.environ["IPTV_PASSWORD"] = password
        success(t("creds_saved"))


def _activate_free():
    """Activa el device (tier free). Devuelve (client|None, status):
      'ok'     -> activado, client usable
      'linked' -> aaa100082: el device quedo atado a una cuenta con password -> usar login
      'failed' -> otro error (red/.env)"""
    client = IPTVClient(auto_activate=False)
    r = client.activate()
    if getattr(client, "user_id", ""):
        return client, "ok"
    if isinstance(r, dict) and str(r.get("_error", "")) == "aaa100082":
        return None, "linked"
    return None, "failed"


def _login_interactive(prefill_user="", prefill_pass=""):
    """Pide email + password (o usa los prefill), hace login y devuelve un client de cuenta
    (is_account=True) o None. Al exito ofrece guardar credenciales para el auto-login."""
    if prefill_user and prefill_pass:
        username, password = prefill_user, prefill_pass
        info(t("using_creds", u=username))
    else:
        info(t("pwd_tip"))
        username = ask(t("email_user"))
        if not username:
            warn(t("email_required")); return None
        password = ask_secret(t("enc_password"))   # prompt OCULTO
    if not password:
        warn(t("pwd_required")); return None
    info(t("logging_in"))
    client = IPTVClient(auto_activate=False)
    result = client.login(username, password)
    if _is_err(result) or not client.user_id:
        error(t("login_failed", msg=_err_msg(result)))
        return None
    client.is_account = True
    success(f"{t('logged_in')} -- userId={client.user_id}")
    already = (os.environ.get("IPTV_USERNAME") == username and os.environ.get("IPTV_PASSWORD") == password)
    if not already and confirm(t("save_creds"), default=True):
        env_path = _env_dir() / ".env"
        _update_env_var(env_path, "IPTV_USERNAME", username)
        _update_env_var(env_path, "IPTV_PASSWORD", password)
        os.environ["IPTV_USERNAME"] = username
        os.environ["IPTV_PASSWORD"] = password
        success(t("creds_saved"))
    return client


def _new_anonymous(persist=True):
    """Provisiona un device ANONIMO nuevo (modo free) via v3/snToken + v8/active, sin tocar
    ninguna cuenta. Si persist=True guarda el SN nuevo en .env para las proximas corridas.
    Devuelve el client free o None."""
    info(t("provisioning"))
    c = IPTVClient(auto_activate=False)
    r = c.new_anonymous_device()
    if not (isinstance(r, dict) and r.get("userToken")):
        error(t("provision_failed", msg=_err_msg(r) if isinstance(r, dict) else str(r)))
        return None
    success(f"{t('connected_free')} -- userId={c.user_id}")
    if persist and r.get("sn"):
        env_path = _env_dir() / ".env"
        _update_env_var(env_path, "IPTV_DEVICE_SN", r["sn"])
        os.environ["IPTV_DEVICE_SN"] = r["sn"]
        success(t("device_saved"))
    return c


def register_account():
    """Flujo de REGISTRO: email + codigo -> validate -> bindEmail -> login. Devuelve client logueado o None.

    Secuencia (verificada, ver MAGIA_RUNBOOK.md §11):
      sendEmailVerifyCode(type=1) -> validateVerifyCode(type=1) -> bindEmail(type=1) -> login.
    El validate es OBLIGATORIO antes del bind (sin el, el server responde 'codigo no coincide')."""
    email = ask(t("email_user"))
    if not email:
        warn(t("email_required")); return None
    info(t("pwd_tip"))
    password = ask_secret(t("enc_password"))
    if not password:
        warn(t("pwd_required")); return None
    client = IPTVClient()  # cuenta de device (userId/userToken para los requests)
    if not getattr(client, "user_id", None):
        error(t("not_activated")); return None
    info(t("sending_code", email=email))
    r = client.send_email_verify_code(email, type_="1")
    if _is_err(r):
        error(t("code_send_fail", msg=_err_msg(r)))
        return None
    success(t("code_sent"))
    info(t("check_email_hint"))
    code = ask(t("verify_code"))
    if not code:
        warn(t("code_required")); return None
    info(t("validating_code"))
    rv = client.validate_verify_code(email, code, type_="1")       # requerido antes del bind
    if _is_err(rv) or (isinstance(rv, dict) and str(rv.get("returnCode", "0")) not in ("0", "")):
        error(t("code_send_fail", msg=_err_msg(rv) or rv.get("errorMessage", "")))
        return None
    success(t("code_ok"))
    info(t("creating_account"))
    rb = client.bind_email(email, password, type_="1")
    if _is_err(rb):
        if "100077" in str(rb.get("_error", "")):              # aaa100077 = email ya bindeado
            error(t("email_in_use")); info(t("one_email_note"))
        else:
            error(t("register_fail", msg=_err_msg(rb)))
        return None
    info(t("logging_in"))
    c2 = IPTVClient(auto_activate=False)
    rl = c2.login(email, password)
    if isinstance(rl, dict) and rl.get("userToken"):
        success(f"{t('registered')} -- userId={c2.user_id}")
        _maybe_save_creds(email, password)
        return c2
    error(t("login_failed", msg=_err_msg(rl or {})))
    return None


def recover_password():
    """Flujo de RECUPERAR CONTRASENA: email + codigo -> resetPwd -> login. Devuelve client o None."""
    email = ask(t("email_user"))
    if not email:
        warn(t("email_required")); return None
    client = IPTVClient()
    if not getattr(client, "user_id", None):
        error(t("not_activated")); return None
    info(t("sending_code", email=email))
    r = client.send_email_verify_code(email, type_="3")
    if _is_err(r):
        error(t("code_send_fail", msg=_err_msg(r)))
        return None
    success(t("code_sent"))
    info(t("check_email_hint"))
    code = ask(t("verify_code"))
    if not code:
        warn(t("code_required")); return None
    info(t("pwd_tip"))
    newpass = ask_secret(t("new_password"))
    if not newpass:
        warn(t("newpwd_required")); return None
    info(t("resetting"))
    rr = client.reset_pwd(email, newpass, code, type_="3")
    if _is_err(rr):
        error(t("reset_fail", msg=_err_msg(rr)))
        return None
    info(t("logging_in"))
    c2 = IPTVClient(auto_activate=False)
    rl = c2.login(email, newpass)
    if isinstance(rl, dict) and rl.get("userToken"):
        success(f"{t('pwd_reset_ok')} -- userId={c2.user_id}")
        _maybe_save_creds(email, newpass)
        return c2
    error(t("login_failed", msg=_err_msg(rl or {})))
    return None


# ─── Main ───
def main():
    global LANG
    os.system("cls" if os.name == "nt" else "clear")
    banner()

    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        return

    if "--es" in sys.argv:
        LANG = "es"
    elif "--en" in sys.argv:
        LANG = "en"
    else:
        saved = os.environ.get("MAGIA_LANG", "")
        if saved in ("en", "es"):
            LANG = saved
        else:
            lang_choices = [
                ("English", "menus and messages in English"),
                ("Espanol", "menus y mensajes en espanol"),
            ]
            lang_idx = select_menu(t("lang_prompt"), lang_choices, back=False)
            LANG = "es" if lang_idx == 1 else "en"
            env_path = _env_dir() / ".env"
            if env_path.exists():
                _update_env_var(env_path, "MAGIA_LANG", LANG)
            os.environ["MAGIA_LANG"] = LANG

    ready, reason = env_is_ready()
    if not ready:
        run_setup(reason)

    _ensure_ffmpeg()

    # Auth
    section(t("auth"))
    env_user = os.environ.get("IPTV_USERNAME", "")
    env_pass = os.environ.get("IPTV_PASSWORD", "")
    force_free = "--free" in sys.argv
    force_menu = any(f in sys.argv for f in ("--switch", "--login", "--menu"))
    force_new_device = any(f in sys.argv for f in ("--new-device", "--reset-device"))

    def _free_or_login(pf_user="", pf_pass=""):
        """Activa el tier free; si el device quedo atado a una cuenta (aaa100082) provisiona un
        device anonimo NUEVO (sin tocar la cuenta). Devuelve un client usable o None."""
        c, status = _activate_free()
        if status == "ok":
            success(f"{t('connected_free')} -- userId={c.user_id}")
            return c
        if status == "linked":
            warn(t("device_linked"))
            return _new_anonymous(persist=True)
        error(t("not_activated"))
        return None

    client = None

    # AUTO-LOGIN / arranque:
    #   magia --switch      -> menu (cambiar cuenta / registrar / recuperar / logout)
    #   magia --free        -> tier free por esta corrida (usa el device actual)
    #   magia --new-device  -> provisiona un device anonimo NUEVO (modo free)
    if force_new_device:
        client = _new_anonymous(persist=True)
        if client is None:
            return
    elif force_free:
        info(t("activating"))
        client = _free_or_login(env_user, env_pass)
        if client is None:
            return
    elif env_user and env_pass and not force_menu:
        info(t("using_creds", u=env_user))
        info(t("logging_in"))
        client = IPTVClient(auto_activate=False)
        result = client.login(env_user, env_pass)
        if _is_err(result) or not client.user_id:
            error(t("login_failed", msg=_err_msg(result)))
            warn(t("relogin_menu"))
            client = None                      # credenciales invalidas -> cae al menu
        else:
            client.is_account = True
            success(f"{t('logged_in')} -- userId={client.user_id}")
            info(t("switch_hint"))

    if client is None:
        auth_choices = [
            (t("free_tier"), t("free_hint")),
            (t("login_account"), t("login_hint")),
            (t("register"), t("register_hint")),
            (t("recover_pwd"), t("recover_hint")),
        ]
        if env_user and env_pass:
            auth_choices.append((t("logout"), t("logout_hint")))   # idx 4
        auth_idx = select_menu(t("select_auth"), auth_choices, back=False)
        if auth_idx is None:
            return

        info(t("connecting"))

        if auth_idx == 2:
            # Registro (email nuevo + codigo). Si falla, cae a free (o login si el device esta atado).
            client = register_account()
            if client is None:
                warn(t("fallback_free")); client = _free_or_login(env_user, env_pass)
                if client is None:
                    return
            else:
                client.is_account = True
        elif auth_idx == 3:
            # Recuperar contrasena (email + codigo). Si falla, cae a free (o login).
            client = recover_password()
            if client is None:
                warn(t("fallback_free")); client = _free_or_login(env_user, env_pass)
                if client is None:
                    return
            else:
                client.is_account = True
        elif auth_idx == 4:
            # Logout: borra credenciales guardadas y sale (Salir mantiene la sesion).
            _clear_saved_creds()
            success(t("logged_out"))
            console.print(f"\n  [dim]{t('bye')}[/dim]\n")
            return
        elif auth_idx == 0:
            info(t("activating"))
            client = _free_or_login(env_user, env_pass)
            if client is None:
                return
        else:
            # Login manual (idx 1). Credenciales frescas (no reusar las guardadas que ya fallaron).
            client = _login_interactive()
            if client is None:
                warn(t("fallback_free"))
                client = _free_or_login()
                if client is None:
                    return

    # CDN auth
    info(t("cdn_auth"))
    time.sleep(API_DELAY)
    cdn_base, cf_auth = get_cf_vod_auth(client)
    if cdn_base:
        exp_match = re.search(r"expired=(\d+)", cf_auth or "")
        if exp_match:
            remaining_h = (int(exp_match.group(1)) - time.time()) / 3600
            success(f"{t('cdn_ready')} -- {t('cdn_valid', h=remaining_h)}")
        else:
            success(t("cdn_ready"))
    else:
        warn(t("cdn_no_cf"))

    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)

    # Main loop
    while True:
        section(t("main_menu"))
        tg_label = f"{t('telegram')} (ON)" if tg.is_configured() else t("telegram")
        menu = [
            (f"⌕ {t('search')}",          t("search_hint")),
            (f"✦ {t('latest')}",          t("latest_hint")),
            (f"◆ {t('by_genre')}",        t("genre_hint")),
            (f"◷ {t('by_year')}",         t("year_hint")),
            (f"◍ {t('by_country')}",      t("country_hint")),
            (f"☺ {t('by_person')}",       t("person_hint")),
            (f"★ {t('recommendations')}", t("rec_hint")),
            (f"▶ {t('live_tv')}",         t("live_hint"), "fg:ansigreen"),   # playback -> verde
            (f"➤ {tg_label}",             t("telegram_hint")),
            (f"? {t('help')}",            t("help_hint")),
        ]
        # "Cerrar sesion" solo si estamos en una sesion de CUENTA (no free tier).
        # Se pone antes de "Salir": Salir mantiene la sesion; Cerrar sesion la olvida.
        logout_idx = None
        if getattr(client, "is_account", False):
            logout_idx = len(menu)
            menu.append((f"⎋ {t('logout')}", t("logout_hint"), "fg:ansired"))
        exit_idx = len(menu)
        menu.append((f"✕ {t('exit')}", "", "fg:ansired"))

        idx = select_menu(t("select"), menu, back=False)
        if idx is None or idx == exit_idx:
            console.print(f"\n  [dim]{t('bye')}[/dim]\n")
            break
        if logout_idx is not None and idx == logout_idx:
            client.logout()                 # avisa al server (v5/loginOut), como el app
            _clear_saved_creds()            # olvida las credenciales locales (corta auto-login)
            success(t("logged_out"))
            console.print(f"\n  [dim]{t('bye')}[/dim]\n")
            break

        if idx == 0:
            item = do_search(client)
            handle_item(client, item, cdn_base, cf_auth, DEFAULT_OUT)
        elif idx == 1:
            item = browse_catalog(client, query="s", label=t("latest"))
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
            configure_telegram()
        elif idx == 9:
            show_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n\n  [dim]Interrupted. Bye![/dim]\n")
        sys.exit(0)
