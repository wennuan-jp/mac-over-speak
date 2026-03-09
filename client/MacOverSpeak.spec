# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['qwen_bridge.py'],
    pathex=['..', '/Users/wennuan/dev/infra/asr-llm/Qwen3-ASR/'],
    binaries=[],
    datas=[
        ('../api', 'api'),
        ('/Users/wennuan/miniconda3/envs/qwen3-asr/lib/python3.12/site-packages/nagisa/data', 'nagisa/data')
    ],
    hiddenimports=[
        'api.settings',
        'api.urls',
        'api.views',
        'api.asr_engine',
        'qwen_asr',
        'qwen_asr.inference',
        'qwen_asr.inference.qwen3_asr',
        'qwen_asr.inference.utils',
        'qwen_asr.core',
        'qwen_asr.core.transformers_backend',
        'nagisa',
        'nagisa.prepro',
        'nagisa.train',
        'nagisa.tagger',
        'nagisa.model',
        'nagisa.mecab_system_eval',
        'torch',
        'transformers',
        'soundfile',
        'scipy',
        'django',
        'objc',
        'AppKit',
        'ApplicationServices',
        'rumps',
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MacOverSpeak',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MacOverSpeak',
)
app = BUNDLE(
    coll,
    name='MacOverSpeak.app',
    icon=None,
    bundle_identifier='com.wennuan.macoverspeak',
    info_plist={
        'NSAccessibilityUsageDescription': 'Mac Over Speak needs Accessibility permissions to listen for global hotkeys and simulate typing.',
        'LSUIElement': False, # Set to True if you want it to behave like a background app (no dock icon after specific setup)
    },
)
