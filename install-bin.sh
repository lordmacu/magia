#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════╗
# ║  Magia — Instalador de binario precompilado              ║
# ║  No requiere Python ni dependencias                      ║
# ║  Uso:  curl -sL <URL>/install-bin.sh | bash              ║
# ╚═══════════════════════════════════════════════════════════╝
set -euo pipefail

REPO="lordmacu/magia"
INSTALL_DIR="$HOME/.local/bin"

R='\033[0m' B='\033[1m' C='\033[96m' G='\033[92m' Y='\033[93m' RED='\033[91m' D='\033[2m'

info()    { echo -e "  ${C}i${R}  $1"; }
ok()      { echo -e "  ${G}✓${R}  $1"; }
warn()    { echo -e "  ${Y}!${R}  $1"; }
fail()    { echo -e "  ${RED}x${R}  $1"; exit 1; }

echo ""
echo -e "${C}${B}"
echo "  ███╗   ███╗ █████╗  ██████╗ ██╗ █████╗ "
echo "  ████╗ ████║██╔══██╗██╔════╝ ██║██╔══██╗"
echo "  ██╔████╔██║███████║██║  ███╗██║███████║"
echo "  ██║╚██╔╝██║██╔══██║██║   ██║██║██╔══██║"
echo "  ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║██║  ██║"
echo "  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═╝"
echo -e "${R}"
echo -e "  ${D}Binary Installer${R}"
echo ""

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux*)   ASSET="magia-linux" ;;
    Darwin*)  ASSET="magia-macos" ;;
    *)        fail "Unsupported OS: $OS. Use the Python installer or download from GitHub." ;;
esac

info "Platform: $OS ($ARCH)"

# Get latest release URL
info "Checking latest release..."

if command -v curl &>/dev/null; then
    DL="curl -sL"
    DL_OUT="curl -sL -o"
elif command -v wget &>/dev/null; then
    DL="wget -qO-"
    DL_OUT="wget -q -O"
else
    fail "curl or wget required"
fi

LATEST_URL=$($DL "https://api.github.com/repos/$REPO/releases/latest" | grep -o "\"browser_download_url\".*$ASSET\"" | head -1 | cut -d'"' -f4)

if [ -z "$LATEST_URL" ]; then
    fail "No release found. Create one first with: git tag v1.0.0 && git push --tags
         Or use the Python installer: curl -sL https://raw.githubusercontent.com/$REPO/main/install.sh | bash"
fi

ok "Found: $LATEST_URL"

# Download
mkdir -p "$INSTALL_DIR"
DEST="$INSTALL_DIR/magia"

info "Downloading to $DEST..."
$DL_OUT "$DEST" "$LATEST_URL" || fail "Download failed"
chmod +x "$DEST"
ok "Downloaded ($( (stat -f%z "$DEST" 2>/dev/null || stat -c%s "$DEST" 2>/dev/null) | awk '{printf "%.1f MB", $1/1048576}' ))"

# Verify it runs
if "$DEST" --help &>/dev/null 2>&1; then
    ok "Binary works"
else
    warn "Binary may not work on this system. Try: $DEST"
fi

# Check PATH
if echo "$PATH" | grep -q "$INSTALL_DIR"; then
    ok "'magia' command ready"
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
            ok "PATH updated in $SHELL_RC"
        fi
    fi
    warn "Run: export PATH=\"\$HOME/.local/bin:\$PATH\"  (or open a new terminal)"
fi

echo ""
echo -e "  ${G}${B}╔═══════════════════════════════════════════╗${R}"
echo -e "  ${G}${B}║       Magia installed successfully!       ║${R}"
echo -e "  ${G}${B}╚═══════════════════════════════════════════╝${R}"
echo ""
echo -e "  ${B}To start:${R}"
echo -e "    ${C}magia${R}"
echo ""
echo -e "  ${D}No Python required — standalone binary.${R}"
echo -e "  ${D}Config will be saved to ~/.magia/.env on first run.${R}"
echo ""
