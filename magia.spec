# PyInstaller spec for Magia
# Build: pyinstaller magia.spec

import sys

a = Analysis(
    ['magia.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('.env.example', '.'),
    ],
    hiddenimports=[
        'iptv_client',
        'telegram_notifier',
        'Crypto.Cipher.DES3',
        'Crypto.Util.Padding',
        'rich',
        'rich.console',
        'rich.panel',
        'rich.table',
        'rich.text',
        'rich.progress',
        'rich.columns',
        'rich.rule',
        'rich.align',
        'rich.box',
        'InquirerPy',
        'InquirerPy.separator',
        'InquirerPy.prompts.list',
        'InquirerPy.prompts.input',
        'InquirerPy.prompts.confirm',
        'InquirerPy.prompts.filepath',
        'InquirerPy.utils',
        'InquirerPy.base',
        'InquirerPy.base.control',
        'prompt_toolkit',
        'prompt_toolkit.application',
        'prompt_toolkit.output',
        'prompt_toolkit.input',
        'pfzy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'xmlrpc', 'pydoc'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='magia',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True if sys.platform != 'win32' else False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
