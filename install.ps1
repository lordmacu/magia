# ╔═══════════════════════════════════════════════════════════╗
# ║  Magia — Windows Installer                               ║
# ║  Usage:  powershell -c "irm https://raw.githubusercontent.com/lordmacu/magia/main/install.ps1 | iex"
# ╚═══════════════════════════════════════════════════════════╝

$ErrorActionPreference = "Stop"
$REPO_URL = "https://github.com/lordmacu/magia"
$INSTALL_DIR = "$env:USERPROFILE\magia"
$BRANCH = "main"

function Write-Color($color, $symbol, $msg) {
    Write-Host "  " -NoNewline
    Write-Host $symbol -ForegroundColor $color -NoNewline
    Write-Host "  $msg"
}
function Info($msg)    { Write-Color Cyan    "i" $msg }
function Ok($msg)      { Write-Color Green   "+" $msg }
function Warn($msg)    { Write-Color Yellow  "!" $msg }
function Fail($msg)    { Write-Color Red     "x" $msg; exit 1 }
function Step($msg)    { Write-Host "`n  -- $msg --" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  MAGIA Installer for Windows" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════
# 1. Check Python
# ═══════════════════════════════════════
Step "Checking Python"

$PYTHON = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+\.\d+)") {
            $major, $minor = $Matches[1] -split '\.'
            if ([int]$major -ge 3 -and [int]$minor -ge 8) {
                $PYTHON = $cmd
                break
            }
        }
    } catch {}
}

if (-not $PYTHON) {
    Warn "Python >= 3.8 not found. Attempting to install..."

    $installed = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing with winget..."
        try {
            winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
            $installed = $true
        } catch {}
    }
    if (-not $installed -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Info "Installing with Chocolatey..."
        try {
            choco install python3 -y 2>&1 | Out-Null
            $installed = $true
        } catch {}
    }
    if (-not $installed) {
        Info "Downloading Python installer from python.org..."
        $pyUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
        $pyInstaller = "$env:TEMP\python-installer.exe"
        try {
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
            Info "Running installer (this may take a minute)..."
            Start-Process -Wait -FilePath $pyInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1"
            Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue
            $installed = $true
        } catch {
            Fail "Could not download or run Python installer. Install manually: https://python.org/downloads"
        }
    }

    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")

    $PYTHON = $null
    foreach ($cmd in @("python3", "python", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python (\d+\.\d+)") {
                $major, $minor = $Matches[1] -split '\.'
                if ([int]$major -ge 3 -and [int]$minor -ge 8) {
                    $PYTHON = $cmd
                    break
                }
            }
        } catch {}
    }

    if (-not $PYTHON) {
        Fail "Python installation failed. Install manually: https://python.org/downloads"
    }
    Ok "Python installed: $PYTHON ($ver)"
} else {
    Ok "Python found: $PYTHON ($ver)"
}

# ═══════════════════════════════════════
# 2. Check pip
# ═══════════════════════════════════════
Step "Checking pip"

$hasPip = $false
try {
    & $PYTHON -m pip --version 2>&1 | Out-Null
    $hasPip = $true
} catch {}

if (-not $hasPip) {
    Warn "pip not found, attempting install..."
    try {
        & $PYTHON -m ensurepip --upgrade 2>&1 | Out-Null
        $hasPip = $true
    } catch {
        Fail "Could not install pip. Run: $PYTHON -m ensurepip --upgrade"
    }
}
Ok "pip available"

# ═══════════════════════════════════════
# 3. Download Magia
# ═══════════════════════════════════════
Step "Downloading Magia"

if (Test-Path "$INSTALL_DIR\.git") {
    Info "Existing installation found, updating..."
    Push-Location $INSTALL_DIR
    try {
        git fetch origin $BRANCH 2>&1 | Out-Null
        git reset --hard "origin/$BRANCH" 2>&1 | Out-Null
        Ok "Updated"
    } catch {
        Warn "git update failed, re-downloading..."
        Pop-Location
        Remove-Item $INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        git clone --depth 1 -b $BRANCH $REPO_URL $INSTALL_DIR 2>&1 | Out-Null
        if (-not $?) { Fail "Could not clone. Check the URL: $REPO_URL" }
        Push-Location $INSTALL_DIR
        Ok "Re-downloaded"
    }
    Pop-Location
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    Info "Cloning repository..."
    git clone --depth 1 -b $BRANCH $REPO_URL $INSTALL_DIR 2>&1 | Out-Null
    if (-not $?) { Fail "Could not clone. Check the URL: $REPO_URL" }
    Ok "Cloned to $INSTALL_DIR"
} else {
    Info "git not available, downloading as ZIP..."
    $zipUrl = "$REPO_URL/archive/refs/heads/$BRANCH.zip"
    $tmpZip = [System.IO.Path]::GetTempFileName() + ".zip"
    $tmpDir = [System.IO.Path]::GetTempFileName() + "_extract"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip -UseBasicParsing
        Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
        $extracted = Get-ChildItem $tmpDir | Select-Object -First 1
        if (-not (Test-Path $INSTALL_DIR)) { New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null }
        Copy-Item "$($extracted.FullName)\*" $INSTALL_DIR -Recurse -Force
        Remove-Item $tmpZip -Force
        Remove-Item $tmpDir -Recurse -Force
        Ok "Downloaded to $INSTALL_DIR"
    } catch {
        Fail "Download failed. Check your connection."
    }
}

# ═══════════════════════════════════════
# 4. Install Python dependencies
# ═══════════════════════════════════════
Step "Installing dependencies"

$deps = @("pycryptodome", "requests", "rich", "InquirerPy", "unicorn")
foreach ($dep in $deps) {
    $importName = if ($dep -eq "pycryptodome") { "Crypto" } else { $dep }
    $installed = $false
    try {
        & $PYTHON -c "import $importName" 2>&1 | Out-Null
        $installed = $true
    } catch {}

    if ($installed) {
        Ok "$dep already installed"
    } else {
        Info "Installing $dep..."
        try {
            & $PYTHON -m pip install --user $dep -q 2>&1 | Out-Null
            Ok "$dep installed"
        } catch {
            try {
                & $PYTHON -m pip install $dep -q 2>&1 | Out-Null
                Ok "$dep installed"
            } catch {
                Fail "Could not install $dep"
            }
        }
    }
}

# ═══════════════════════════════════════
# 5. Configure .env (interactive)
# ═══════════════════════════════════════
Step "Configuring environment"

$envFile = "$INSTALL_DIR\.env"
$skipEnv = $false

if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    $requiredVars = @("IPTV_3DES_KEY", "IPTV_HOSTS", "IPTV_APP_ID", "IPTV_DEVICE_SN")
    $envComplete = $true
    foreach ($v in $requiredVars) {
        if ($envContent -notmatch "(?m)^${v}=.+") {
            $envComplete = $false
            break
        }
    }
    if ($envComplete) {
        Ok ".env already configured, keeping it"
        $skipEnv = $true
    } else {
        Warn ".env exists but has empty required fields"
        $reconf = Read-Host "  ?  Reconfigure .env? (y/N)"
        if ($reconf -ne "y" -and $reconf -ne "Y") {
            Ok "Keeping existing .env"
            $skipEnv = $true
        }
    }
}

if (-not $skipEnv) {
    Write-Host ""
    Write-Host "  Magia needs credentials from the IPTV app to work." -ForegroundColor White
    Write-Host "  These come from APK analysis (see README for details)." -ForegroundColor DarkGray
    Write-Host ""

    function Ask-Val($prompt, $default) {
        if ($default) {
            $val = Read-Host "  >  $prompt [$default]"
            if (-not $val) { $val = $default }
        } else {
            $val = Read-Host "  >  $prompt"
        }
        return $val
    }

    Write-Host "  -- Required --" -ForegroundColor Cyan
    $env3DES     = Ask-Val "3DES Key (48 hex chars)"
    $envHosts    = Ask-Val "API Hosts (comma-separated)"
    $envAppId    = Ask-Val "App ID"
    $envSN       = Ask-Val "Device SN"
    Write-Host ""
    Write-Host "  -- Optional (press Enter to skip) --" -ForegroundColor Cyan
    $envApkVer   = Ask-Val "APK Version" "49902"
    $envDRM      = Ask-Val "Device DRM ID"
    $envToken    = Ask-Val "Device Token"
    $envReserve1 = Ask-Val "Device Reserve1"
    $envUser     = Ask-Val "Login username/email"
    $envPass     = Ask-Val "Login encrypted password"
    $envDlDir    = Ask-Val "Download directory" "downloads"

    @"
# IPTV Portal Configuration (generated by install.ps1)

# 3DES encryption key (hex, 48 chars)
IPTV_3DES_KEY=$env3DES

# API hosts (comma-separated, primary + fallback)
IPTV_HOSTS=$envHosts

# Device fingerprint (only SN is required)
IPTV_DEVICE_SN=$envSN

# APK identity
IPTV_APP_ID=$envAppId

# Optional device/APK fields (server accepts empty)
IPTV_APK_VERSION=$envApkVer
IPTV_DEVICE_DRM_ID=$envDRM
IPTV_DEVICE_TOKEN=$envToken
IPTV_DEVICE_RESERVE1=$envReserve1

# Login credentials (optional)
IPTV_USERNAME=$envUser
IPTV_PASSWORD=$envPass

# Download settings
IPTV_DOWNLOAD_DIR=$envDlDir
"@ | Set-Content -Path $envFile -Encoding UTF8

    Ok ".env created at $envFile"
}

# ═══════════════════════════════════════
# 6. Create batch wrapper
# ═══════════════════════════════════════
Step "Creating 'magia' command"

$wrapperDir = "$env:USERPROFILE\.local\bin"
if (-not (Test-Path $wrapperDir)) { New-Item -ItemType Directory -Path $wrapperDir -Force | Out-Null }

$wrapperBat = "$wrapperDir\magia.bat"
@"
@echo off
cd /d "$INSTALL_DIR" && $PYTHON magia.py %*
"@ | Set-Content -Path $wrapperBat -Encoding ASCII

Ok "Command created at $wrapperBat"

# Check PATH
if ($env:PATH -notlike "*$wrapperDir*") {
    Warn "Add to PATH: $wrapperDir"
    Warn "Run: [Environment]::SetEnvironmentVariable('PATH', `"$wrapperDir;`" + [Environment]::GetEnvironmentVariable('PATH','User'), 'User')"
}

# ═══════════════════════════════════════
# 7. Verify
# ═══════════════════════════════════════
Step "Verification"

Push-Location $INSTALL_DIR
try {
    & $PYTHON -c "import rich, InquirerPy, requests, Crypto, unicorn; from iptv_client import IPTVClient; print('  Modules OK')" 2>&1 | Out-Null
    Ok "All modules load correctly"
} catch {
    Warn "Module verification failed (may still work)"
}
Pop-Location

Write-Host ""
Write-Host "  +=============================================+" -ForegroundColor Green
Write-Host "  |       Magia installed successfully!         |" -ForegroundColor Green
Write-Host "  +=============================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  To start:" -ForegroundColor White
Write-Host "    magia                                   (if PATH configured)" -ForegroundColor Cyan
Write-Host "    cd $INSTALL_DIR && $PYTHON magia.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Configuration:" -ForegroundColor White
Write-Host "    $envFile" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Downloads in:" -ForegroundColor White
Write-Host "    $INSTALL_DIR\downloads\" -ForegroundColor DarkGray
Write-Host ""
