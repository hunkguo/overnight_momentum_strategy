# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Overnight Momentum Strategy.

用法:
    venv\\Scripts\\pyinstaller oms.spec --clean --noconfirm

产物:
    dist\\oms.exe

注意: tqcenter 不打包进 exe — 它随通达信终端发布，运行时通过
`sys.path.append(config.TDX_USER_PATH)` 引入。因此产出的 exe 仍需
要在装有通达信金融终端的机器上运行。
"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
datas = []
binaries = []

# 只需要保证 pandas / numpy 的子模块收录齐
for pkg in ("pandas", "numpy"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "IPython",
        "notebook",
        "jupyter",
        "sphinx",
        "pytest",
        "akshare",
        "mini_racer",
        "curl_cffi",
        "py_mini_racer",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="oms",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
