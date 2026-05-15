from setuptools import setup

APP = ['main.py']
DATA_FILES = ['assets']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'assets/AppIcon.icns',
    'plist': {
        'CFBundleName': 'MovWall',
        'CFBundleDisplayName': 'MovWall',
        'CFBundleIdentifier': 'com.movwall.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,
        'NSHumanReadableCopyright': 'Copyright © 2026 aliyabuz25',
    },
    'packages': ['AppKit', 'Foundation', 'AVFoundation', 'AVKit', 'Quartz', 'CoreMedia'],
}

setup(
    app=APP,
    name='MovWall',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
