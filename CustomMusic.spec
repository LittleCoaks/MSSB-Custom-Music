# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build for Custom Music.

    pyinstaller --clean --noconfirm CustomMusic.spec

Produces a single self-contained file (a .app bundle on macOS) in dist/.
numpy and miniaudio are bundled, so the released build encodes at full speed and
reads MP3/FLAC/OGG with nothing for the user to install.
"""

import os
import sys

block_cipher = None

NAME = 'CustomMusic'
ICON = None
for _cand in ('icon.ico', 'icon.icns'):
    if os.path.exists(_cand):
        ICON = _cand
        break

a = Analysis(
    ['custom_music.py'],
    pathex=[],
    binaries=[],
    datas=[('README.md', '.')],
    hiddenimports=[
        # Reached only through optional imports, so PyInstaller cannot see them.
        'miniaudio',
        'numpy',
        # miniaudio is a cffi extension: _miniaudio.pyd gets picked up, but the
        # cffi runtime it imports at load time does not, and the resulting
        # ImportError just looks like "no decoder installed".
        '_miniaudio',
        '_cffi_backend',
        'cffi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Nothing here uses these; they are what makes a numpy build huge.
        'matplotlib', 'scipy', 'pandas', 'PIL', 'pytest', 'setuptools',
        'pydoc_data', 'numpy.f2py', 'numpy.testing', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows and Linux build as console programs so command-line use behaves the
# way scripts expect: the shell waits for it, and redirection works.  A GUI
# subsystem binary on Windows does neither -- PowerShell returns immediately,
# which would let a batch file carry on before the encode had finished.  The
# console window that would otherwise appear on a double-click is hidden at
# startup by apppaths.hide_own_console().
# macOS has no such split; there the .app bundle below is what users launch.
CONSOLE = sys.platform != 'darwin'

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name=NAME + '.app',
        icon=ICON,
        bundle_identifier='com.projectrio.custommusic',
        info_plist={
            'CFBundleName': 'Custom Music',
            'CFBundleDisplayName': 'Custom Music',
            'NSHighResolutionCapable': True,
            # Without this the .app cannot be opened from Terminal with args.
            'LSMultipleInstancesProhibited': False,
        },
    )
