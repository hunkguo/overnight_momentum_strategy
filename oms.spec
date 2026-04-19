# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Overnight Momentum Strategy.

用法:
    venv\\Scripts\\pyinstaller oms.spec --clean --noconfirm

产物:
    dist\\oms.exe (single-file, ~80MB)
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

# akshare 及其底层 HTTP / JS 引擎依赖：都要完整收录
hiddenimports = []
datas = []
binaries = []

for pkg in ("akshare", "mini_racer", "curl_cffi", "py_mini_racer"):
    try:
        pdatas, pbinaries, phidden = collect_all(pkg)
        datas += pdatas
        binaries += pbinaries
        hiddenimports += phidden
    except Exception:
        pass

# 保险起见再补子模块
for pkg in ("akshare", "pandas"):
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
        # 剔除常见大体积但本项目用不到的模块
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "IPython",
        "notebook",
        "jupyter",
        "sphinx",
        "pytest",
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
