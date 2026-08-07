# -*- mode: python ; coding: utf-8 -*-
# Gera um único .exe standalone para Windows: `pyinstaller build.spec`
# Os dados do usuário (banco SQLite, PDFs) sao criados em runtime ao lado do .exe,
# nunca dentro deste bundle — ver app/config.py.

datas = [
    ("app/seeds", "app/seeds"),
    ("app/web/templates", "app/web/templates"),
    ("app/web/static", "app/web/static"),
    ("app/db/schema.sql", "app/db"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # psycopg só é usado no modo WEB (Postgres); o desktop roda em SQLite e
    # nem chega a importá-lo — fora do bundle, o instalador não engorda à toa.
    excludes=["psycopg", "psycopg_binary"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EscalaCarrinho",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
