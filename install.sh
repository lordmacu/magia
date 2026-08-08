#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════╗
# ║  Magia — Instalador automático                           ║
# ║  Uso:  curl -sL <URL_RAW>/install.sh | bash              ║
# ║  o:    bash install.sh                                    ║
# ╚═══════════════════════════════════════════════════════════╝
set -euo pipefail

REPO_URL="https://github.com/lordmacu/magia"
INSTALL_DIR="$HOME/magia"
BRANCH="main"
MIN_PYTHON="3.8"

# ─── Colores ───
R='\033[0m' B='\033[1m' C='\033[96m' G='\033[92m' Y='\033[93m' RED='\033[91m' D='\033[2m'

banner() {
    echo ""
    echo -e "${C}${B}"
    echo "  ███╗   ███╗ █████╗  ██████╗ ██╗ █████╗ "
    echo "  ████╗ ████║██╔══██╗██╔════╝ ██║██╔══██╗"
    echo "  ██╔████╔██║███████║██║  ███╗██║███████║"
    echo "  ██║╚██╔╝██║██╔══██║██║   ██║██║██╔══██║"
    echo "  ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║██║  ██║"
    echo "  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═╝"
    echo -e "${R}"
    echo -e "  ${D}Installer v1.0${R}"
    echo ""
}

info()    { echo -e "  ${C}i${R}  $1"; }
ok()      { echo -e "  ${G}✓${R}  $1"; }
warn()    { echo -e "  ${Y}!${R}  $1"; }
fail()    { echo -e "  ${RED}x${R}  $1"; exit 1; }
step()    { echo -e "\n  ${C}${B}── $1 ──${R}"; }

# ─── Comparar versiones semánticas ───
version_gte() {
    printf '%s\n%s' "$2" "$1" | sort -V -C
}

banner

# ═══════════════════════════════════════
# 1. Verificar Python
# ═══════════════════════════════════════
step "Verificando Python"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        if [ -n "$ver" ] && version_gte "$ver" "$MIN_PYTHON"; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python >= $MIN_PYTHON no encontrado. Instálalo primero:
         macOS:   brew install python3
         Ubuntu:  sudo apt install python3 python3-pip
         Windows: https://python.org/downloads"
fi
ok "Python encontrado: $PYTHON ($ver)"

# ═══════════════════════════════════════
# 2. Verificar pip
# ═══════════════════════════════════════
step "Verificando pip"

PIP=""
for cmd in pip3 pip "$PYTHON -m pip"; do
    if $cmd --version &>/dev/null 2>&1; then
        PIP="$cmd"
        break
    fi
done

if [ -z "$PIP" ]; then
    warn "pip no encontrado, intentando instalar..."
    $PYTHON -m ensurepip --upgrade 2>/dev/null || true
    if $PYTHON -m pip --version &>/dev/null 2>&1; then
        PIP="$PYTHON -m pip"
    else
        fail "No se pudo instalar pip. Instálalo manualmente:
             $PYTHON -m ensurepip --upgrade
             o: sudo apt install python3-pip"
    fi
fi
ok "pip encontrado: $($PIP --version 2>&1 | head -1)"

# ═══════════════════════════════════════
# 3. Descargar / Actualizar Magia
# ═══════════════════════════════════════
step "Descargando Magia"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Directorio existente, actualizando..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin "$BRANCH" 2>/dev/null || {
        warn "git pull falló, continuando con versión actual"
    }
    ok "Actualizado"
elif command -v git &>/dev/null; then
    info "Clonando repositorio..."
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
        fail "No se pudo clonar. Verifica la URL: $REPO_URL"
    }
    cd "$INSTALL_DIR"
    ok "Clonado en $INSTALL_DIR"
else
    info "git no disponible, descargando como ZIP..."
    TMP_ZIP=$(mktemp /tmp/magia-XXXXXX.zip)
    curl -sL "$REPO_URL/archive/refs/heads/$BRANCH.zip" -o "$TMP_ZIP" || {
        fail "No se pudo descargar. Verifica tu conexión."
    }
    mkdir -p "$INSTALL_DIR"
    unzip -qo "$TMP_ZIP" -d /tmp/magia-extract
    cp -r /tmp/magia-extract/magia-"$BRANCH"/* "$INSTALL_DIR"/
    rm -rf "$TMP_ZIP" /tmp/magia-extract
    cd "$INSTALL_DIR"
    ok "Descargado en $INSTALL_DIR"
fi

# ═══════════════════════════════════════
# 4. Instalar dependencias Python
# ═══════════════════════════════════════
step "Instalando dependencias"

DEPS="pycryptodome requests"
for dep in $DEPS; do
    if $PYTHON -c "import ${dep/pycryptodome/Crypto}" 2>/dev/null; then
        ok "$dep ya instalado"
    else
        info "Instalando $dep..."
        $PIP install --user "$dep" -q 2>/dev/null || $PIP install "$dep" -q || {
            fail "No se pudo instalar $dep"
        }
        ok "$dep instalado"
    fi
done

# ═══════════════════════════════════════
# 5. Configurar .env (interactivo)
# ═══════════════════════════════════════
step "Configurando entorno"

if [ -f "$INSTALL_DIR/.env" ]; then
    ok ".env ya existe"
    echo ""
    echo -ne "  ${Y}?${R}  Reconfigure .env? (y/N): "
    read -r RECONF
    if [ "$RECONF" != "y" ] && [ "$RECONF" != "Y" ]; then
        ok "Keeping existing .env"
        SKIP_ENV=1
    else
        SKIP_ENV=0
    fi
else
    SKIP_ENV=0
fi

if [ "${SKIP_ENV:-0}" = "0" ]; then
    echo ""
    echo -e "  ${B}Magia needs credentials from the IPTV app to work.${R}"
    echo -e "  ${D}These come from APK analysis (see README for details).${R}"
    echo ""

    ask_val() {
        local prompt="$1" default="$2" var_name="$3"
        if [ -n "$default" ]; then
            echo -ne "  ${C}>${R} $prompt [${D}$default${R}]: "
        else
            echo -ne "  ${C}>${R} $prompt: "
        fi
        read -r val
        val="${val:-$default}"
        eval "$var_name=\"\$val\""
    }

    echo -e "  ${C}── Required ──${R}"
    ask_val "3DES Key (48 hex chars)" "" ENV_3DES_KEY
    ask_val "API Hosts (comma-separated)" "" ENV_HOSTS
    ask_val "App ID" "" ENV_APP_ID
    ask_val "APK Version" "" ENV_APK_VER
    echo ""
    echo -e "  ${C}── Device Fingerprint ──${R}"
    ask_val "Device SN" "" ENV_SN
    ask_val "Device DRM ID" "" ENV_DRM
    ask_val "Device Token" "" ENV_TOKEN
    ask_val "Device Reserve1" "" ENV_RESERVE1
    echo ""
    echo -e "  ${C}── Optional (press Enter to skip) ──${R}"
    ask_val "Login username/email" "" ENV_USER
    ask_val "Login encrypted password" "" ENV_PASS
    ask_val "Download directory" "downloads" ENV_DLDIR

    cat > "$INSTALL_DIR/.env" << ENVEOF
# IPTV Portal Configuration (generated by install.sh)

# 3DES encryption key (hex, 48 chars)
IPTV_3DES_KEY=$ENV_3DES_KEY

# API hosts (comma-separated, primary + fallback)
IPTV_HOSTS=$ENV_HOSTS

# Device fingerprint
IPTV_DEVICE_SN=$ENV_SN
IPTV_DEVICE_DRM_ID=$ENV_DRM
IPTV_DEVICE_TOKEN=$ENV_TOKEN
IPTV_DEVICE_RESERVE1=$ENV_RESERVE1

# APK identity
IPTV_APP_ID=$ENV_APP_ID
IPTV_APK_VERSION=$ENV_APK_VER

# Login credentials (optional)
IPTV_USERNAME=$ENV_USER
IPTV_PASSWORD=$ENV_PASS

# Download settings
IPTV_DOWNLOAD_DIR=$ENV_DLDIR
ENVEOF

    ok ".env created at $INSTALL_DIR/.env"
fi

# ═══════════════════════════════════════
# 6. Crear script wrapper 'magia'
# ═══════════════════════════════════════
step "Creando comando 'magia'"

WRAPPER="$HOME/.local/bin/magia"
mkdir -p "$(dirname "$WRAPPER")"

cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR" && exec $PYTHON magia.py "\$@"
WRAPPER_EOF
chmod +x "$WRAPPER"

# Verificar que ~/.local/bin está en PATH
if echo "$PATH" | grep -q "$HOME/.local/bin"; then
    ok "Comando 'magia' instalado"
else
    SHELL_RC=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        SHELL_RC="$HOME/.bash_profile"
    fi

    if [ -n "$SHELL_RC" ]; then
        if ! grep -q '.local/bin' "$SHELL_RC" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
            ok "PATH actualizado en $SHELL_RC"
        fi
    fi
    warn "Ejecuta: export PATH=\"\$HOME/.local/bin:\$PATH\"  (o abre terminal nueva)"
fi

# ═══════════════════════════════════════
# 7. Verificación final
# ═══════════════════════════════════════
step "Verificación"

cd "$INSTALL_DIR"
$PYTHON -c "
from iptv_client import IPTVClient
from magia import banner
print('  Módulos OK')
" 2>/dev/null && ok "Todos los módulos cargan correctamente" || warn "Verificación de módulos falló (puede funcionar igual)"

echo ""
echo -e "  ${G}${B}╔═══════════════════════════════════════════╗${R}"
echo -e "  ${G}${B}║       Magia instalado correctamente!      ║${R}"
echo -e "  ${G}${B}╚═══════════════════════════════════════════╝${R}"
echo ""
echo -e "  ${B}Para iniciar:${R}"
echo -e "    ${C}magia${R}                    (si ~/.local/bin está en PATH)"
echo -e "    ${C}cd $INSTALL_DIR && $PYTHON magia.py${R}"
echo ""
echo -e "  ${B}Configuración:${R}"
echo -e "    ${D}$INSTALL_DIR/.env${R}"
echo ""
echo -e "  ${B}Descargas en:${R}"
echo -e "    ${D}$INSTALL_DIR/downloads/${R}"
echo ""
