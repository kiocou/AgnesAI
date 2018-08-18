# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("websockets")
hiddenimports += collect_submodules("multipart")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += collect_submodules("requests")
hiddenimports += collect_submodules("urllib3")
hiddenimports += collect_submodules("certifi")
hiddenimports += collect_submodules("httptools")
hiddenimports += collect_submodules("watchfiles")
hiddenimports += collect_submodules("anyio")
hiddenimports += collect_submodules("h11")
hiddenimports += collect_submodules("idna")
hiddenimports += collect_submodules("charset_normalizer")

datas = [
    ("web", "web"),
    ("config/config.json", "config"),
    ("database/history.db", "database"),
]

a = Analysis(
    ["web_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6",
              "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "scipy",
              "PIL", "cv2", "torch", "tensorflow", "transformers", "diffusers"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AgnesAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
