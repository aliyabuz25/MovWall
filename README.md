# MovWall

MovWall is an animated wallpaper utility focused on a clean desktop widget experience and low system overhead.

**Ali Yabuz tarafından geliştirilmiştir.**

## Platform Support
- macOS: Full feature support (menubar app, overlay widgets, launchd auto-start)
- Linux (including CachyOS): Lightweight fallback mode (no macOS-native UI stack)

## macOS Setup
```bash
python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-AVFoundation pyobjc-framework-AVKit pyobjc-framework-Quartz pyobjc-framework-CoreMedia
python3 main.py
```

Optional start video:
```bash
python3 main.py /absolute/path/video.mov
```

## Auto Start on macOS
Install launch agent:
```bash
./launchd_install.sh
```

Uninstall launch agent:
```bash
./launchd_uninstall.sh
```

## Features
- Animated wallpaper playback
- Overlay system widget (battery / CPU / RAM / now playing)
- Separate ML Helper chat window
- Desktop icon hide/show toggle
- Performance-aware behavior for low battery

## Assets
- Main icon (SVG): `assets/icon.svg`
- PNG fallback icon: `assets/iconTemplate.png`
- App icon: `assets/AppIcon.icns`

## Linux Note
Current repository includes Linux-safe runtime fallback, but macOS-native UI modules are required for full experience.

## License
MIT
