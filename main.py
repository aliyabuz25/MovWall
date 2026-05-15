#!/usr/bin/env python3
import argparse
import json
import os
import sys
import subprocess
import urllib.parse
import urllib.request
import threading
from pathlib import Path

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSOpenPanel,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSWindow,
    NSButton,
    NSTextField,
    NSFont,
    NSEvent,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
    NSWorkspaceDidActivateApplicationNotification,
)
from AVFoundation import AVPlayer, AVPlayerItem, AVPlayerItemDidPlayToEndTimeNotification
from AVKit import AVPlayerView
from CoreMedia import kCMTimeZero
from Foundation import NSObject, NSNotificationCenter, NSURL, NSTimer
from WebKit import WKWebView, WKWebViewConfiguration
from Quartz import CGWindowLevelForKey, kCGDesktopWindowLevelKey

APP_NAME = "MovWall"
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
LIBRARY_PATH = APP_SUPPORT_DIR / "library.json"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
MENU_ICON_SVG_PATH = ASSETS_DIR / "icon.svg"
MENU_ICON_PATH = ASSETS_DIR / "iconTemplate.png"


class LibraryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"items": [], "current": None})

    def _read(self):
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if "items" not in data:
                data["items"] = []
            if "current" not in data:
                data["current"] = None
            return data
        except Exception:
            return {"items": [], "current": None}

    def _write(self, data):
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def list_items(self):
        return self._read()["items"]

    def current(self):
        return self._read()["current"]

    def set_current(self, path):
        data = self._read()
        data["current"] = path
        self._write(data)

    def add(self, path):
        path = str(Path(path).expanduser().resolve())
        data = self._read()
        if path not in data["items"]:
            data["items"].append(path)
        if data["current"] is None:
            data["current"] = path
        self._write(data)

    def remove(self, path):
        data = self._read()
        data["items"] = [x for x in data["items"] if x != path]
        if data["current"] == path:
            data["current"] = data["items"][0] if data["items"] else None
        self._write(data)

    def get_pref(self, key, default=False):
        data = self._read()
        prefs = data.get("prefs", {})
        return prefs.get(key, default)

    def set_pref(self, key, value):
        data = self._read()
        prefs = data.get("prefs", {})
        prefs[key] = bool(value)
        data["prefs"] = prefs
        self._write(data)


class LoopObserver(NSObject):
    def initWithController_(self, controller):
        self = objc.super(LoopObserver, self).init()
        if self is None:
            return None
        self.controller = controller
        return self

    def playerItemDidReachEnd_(self, notification):
        if self.controller.player is not None:
            self.controller.player.seekToTime_(kCMTimeZero)
            if self.controller.should_play_now():
                self.controller.player.play()


class FocusObserver(NSObject):
    def initWithController_(self, controller):
        self = objc.super(FocusObserver, self).init()
        if self is None:
            return None
        self.controller = controller
        return self

    def appDidActivate_(self, notification):
        self.controller.apply_play_policy()


class WallpaperWindow:
    def __init__(self, screen, player):
        frame = screen.frame()
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        desktop_level = CGWindowLevelForKey(kCGDesktopWindowLevelKey)
        self.window.setLevel_(desktop_level)
        self.window.setOpaque_(True)
        self.window.setBackgroundColor_(NSColor.blackColor())
        self.window.setIgnoresMouseEvents_(True)
        self.window.setHasShadow_(False)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.window.setAcceptsMouseMovedEvents_(True)
        self.window.setMovableByWindowBackground_(False)

        player_view = AVPlayerView.alloc().initWithFrame_(((0, 0), (frame.size.width, frame.size.height)))
        player_view.setPlayer_(player)
        player_view.setControlsStyle_(0)
        player_view.setVideoGravity_("AVLayerVideoGravityResizeAspectFill")
        self.window.setContentView_(player_view)
        self.window.orderBack_(None)


class BrandOverlayWindow:
    def __init__(self, screen, controller):
        self.controller = controller
        frame = screen.frame()
        widget_w = 260
        widget_h = min(460, int(frame.size.height * 0.7))
        widget_x = frame.origin.x + 14
        widget_y = frame.origin.y + frame.size.height - widget_h - 26
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((widget_x, widget_y), (widget_w, widget_h)),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        desktop_level = CGWindowLevelForKey(kCGDesktopWindowLevelKey)
        self.window.setLevel_(desktop_level + 220)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setIgnoresMouseEvents_(False)
        self.window.setHasShadow_(False)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        cfg = WKWebViewConfiguration.alloc().init()
        web = WKWebView.alloc().initWithFrame_configuration_(((0, 0), (widget_w, widget_h)), cfg)
        self.web = web
        web.setOpaque_(False)
        web.setValue_forKey_(False, "drawsBackground")
        web.setNavigationDelegate_(controller)
        html = """
        <html><head><meta charset="utf-8" />
        <style>
        html,body{margin:0;padding:0;background:transparent;overflow:hidden}
        #widget{position:fixed;top:12px;left:8px;z-index:9999;color:#fff;font:12px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;width:260px;max-height:68vh;display:flex;flex-direction:column;gap:10px}
        #card,#aicard{width:230px;background:linear-gradient(180deg,rgba(17,17,20,.62),rgba(10,10,12,.52));border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:10px;box-shadow:0 10px 28px rgba(0,0,0,.35);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
        #head{display:flex;align-items:center;gap:8px;padding:2px 2px 8px 2px}
        #brandIcon{width:16px;height:16px;object-fit:contain;opacity:.98}
        #panel{margin-top:6px;border-radius:12px;padding:0;max-height:52vh;overflow-y:auto;overflow-x:hidden;opacity:1;scrollbar-width:thin}
        #panel::-webkit-scrollbar{width:6px}
        #panel::-webkit-scrollbar-thumb{background:rgba(255,255,255,.25);border-radius:10px}
        .row{display:flex;align-items:center;justify-content:space-between;margin:5px 0}
        .l{display:flex;align-items:center;gap:8px}.v{font-variant-numeric:tabular-nums}
        .icon{display:inline-block;position:relative}.icon.battery{width:18px;height:10px;border:1.3px solid #fff;border-radius:2px}
        .icon.battery::after{content:'';position:absolute;right:-3px;top:2px;width:2px;height:4px;background:#fff;border-radius:1px}
        .icon.battery .fill{position:absolute;left:1px;top:1px;bottom:1px;width:20%;border-radius:1px;background:linear-gradient(90deg,#34d399,#22c55e)}
        .icon.cpu,.icon.ram{width:14px;height:14px;border:1.3px solid #fff;border-radius:3px}
        .icon.cpu::before,.icon.ram::before{content:'';position:absolute;inset:3px;border:1px solid rgba(255,255,255,.9);border-radius:2px}
        #chatlog{height:220px;overflow:auto;background:#121317;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px;line-height:1.4}
        .msg{margin:6px 0}
        #askBtn{display:block;width:100%;margin-top:8px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.08);color:#fff;border-radius:8px;padding:8px;cursor:pointer}
        </style></head><body>
        <div id="widget"><div id="card"><div id="head">
        <svg id="brandIcon" viewBox="0 0 24 24" aria-label="MovWall" role="img">
          <rect x="2" y="2" width="20" height="20" rx="5" fill="rgba(255,255,255,.96)"/>
          <path d="M6 17V7h1.6l2.4 4.1L12.4 7H14v10h-1.5V10.9L10.5 14.3h-.7L7.6 10.9V17H6z" fill="rgba(10,10,12,.95)"/>
          <path d="M15.6 17V7h1.5v8.5H20V17h-4.4z" fill="rgba(10,10,12,.95)"/>
        </svg>
        <span style="opacity:.82;font-weight:600">System Widget</span></div>
        <div id="panel">
        <div id="np" class="row" style="display:none;align-items:center;justify-content:flex-start;gap:8px;background:rgba(255,255,255,.06);padding:6px;border-radius:8px;">
        <img id="npi" src="" style="width:30px;height:30px;border-radius:7px;object-fit:cover;background:rgba(255,255,255,.12)" />
        <div style="display:flex;flex-direction:column;min-width:0;">
          <span id="npt" class="v" style="max-width:136px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;">-</span>
          <span id="nps" style="opacity:.78;max-width:136px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">-</span>
        </div>
        </div>
        <div class="row"><div class="l"><span class="icon battery"><span id="batfill" class="fill"></span></span><span>Battery</span></div><span id="battery" class="v">--%</span></div>
        <div class="row"><div class="l"><span class="icon cpu"></span><span>CPU</span></div><span id="cpu" class="v">--%</span></div>
        <div class="row"><div class="l"><span class="icon ram"></span><span>RAM</span></div><span id="ram" class="v">-- GB</span></div>
        </div></div>
        <div id="aicard"><div id="head"><span style="font-weight:700">ML Helper</span></div>
        <button id="askBtn">Open Chat Window</button>
        </div></div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
        <script>
        (function(){
          if(!window.gsap) return;
          gsap.fromTo('#widget',{opacity:0,y:-8},{opacity:1,y:0,duration:.45,ease:'power2.out'});
          gsap.to('#head',{boxShadow:'0 8px 24px rgba(0,0,0,0.30)',duration:1.2,repeat:-1,yoyo:true,ease:'sine.inOut'});
          gsap.to('#batfill',{opacity:.72,duration:.9,repeat:-1,yoyo:true,ease:'sine.inOut'});
          gsap.fromTo('.row',{opacity:.0,x:-6},{opacity:1,x:0,duration:.28,stagger:.05,ease:'power2.out',delay:.12});
          const askBtn=document.getElementById('askBtn');
          askBtn.addEventListener('click', ()=>{ window.location.href='movwall://open-chat'; });
          async function askAI(q){
            const res = await fetch('http://167.86.75.158:11434/api/generate',{
              method:'POST',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify({
                model:'qwen2.5-coder:1.5b',
                prompt:`You are MovWall support assistant. Keep replies concise and practical. User question: ${q}`,
                stream:false
              })
            });
            if(!res.ok) throw new Error('Endpoint error');
            const data = await res.json();
            return (data.response || 'No response').trim();
          }
        })();
        </script>
        </body></html>"""
        web.loadHTMLString_baseURL_(html, None)
        self.window.setContentView_(web)
        self.window.orderFrontRegardless()
        self.window.makeKeyAndOrderFront_(None)

    def update_stats(self, battery_pct, cpu_pct, ram_used):
        js = f"""
        (function(){{
          var b=document.getElementById('battery');
          var r=document.getElementById('ram');
          var f=document.getElementById('batfill');
          var c=document.getElementById('cpu');
          if(b) b.textContent='{battery_pct}%';
          if(c) c.textContent='{cpu_pct}%';
          if(r) r.textContent='{ram_used} GB';
          if(f) f.style.width=Math.max(6, Math.min(100, {battery_pct})) + '%';
        }})();
        """
        self.web.evaluateJavaScript_completionHandler_(js, None)

    def update_now_playing(self, title, artist, time_text, artwork_url):
        t = title.replace("'", "\\'")
        a = artist.replace("'", "\\'")
        tt = time_text.replace("'", "\\'")
        art = artwork_url.replace("'", "\\'")
        js = f"""
        (function(){{
          var wrap=document.getElementById('np');
          var t=document.getElementById('npt');
          var s=document.getElementById('nps');
          var i=document.getElementById('npi');
          if(!wrap||!t||!s||!i) return;
          if('{t}'.length===0) {{ wrap.style.display='none'; return; }}
          wrap.style.display='flex';
          t.textContent='{t}';
          s.textContent='{a} • {tt}';
          if('{art}'.length>0) i.src='{art}';
        }})();
        """
        self.web.evaluateJavaScript_completionHandler_(js, None)


class NotchHUD:
    def __init__(self, controller):
        self.controller = controller
        screen = NSScreen.mainScreen()
        frame = screen.frame()
        w, h = 240, 56
        x = frame.origin.x + (frame.size.width - w) / 2
        y = frame.origin.y + frame.size.height - h - 18
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (w, h)),
            NSWindowStyleMaskTitled | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitleVisibility_(1)
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.94))
        self.window.setLevel_(CGWindowLevelForKey(kCGDesktopWindowLevelKey) + 1000)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.window.setReleasedWhenClosed_(False)

        pause_btn = NSButton.alloc().initWithFrame_(((18, 14), (90, 28)))
        pause_btn.setTitle_("Pause")
        pause_btn.setTarget_(controller)
        pause_btn.setAction_("onHUDPause:")

        play_btn = NSButton.alloc().initWithFrame_(((130, 14), (90, 28)))
        play_btn.setTitle_("Continue")
        play_btn.setTarget_(controller)
        play_btn.setAction_("onHUDContinue:")

        self.window.contentView().addSubview_(pause_btn)
        self.window.contentView().addSubview_(play_btn)
        self.hide_timer = None

    def show_temporarily(self):
        self.window.orderFrontRegardless()
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
        self.hide_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.4, self, "hideNow:", None, False
        )

    def hideNow_(self, _timer):
        self.window.orderOut_(None)


class AppController(NSObject):
    def init(self):
        self = objc.super(AppController, self).init()
        if self is None:
            return None
        self.store = LibraryStore(LIBRARY_PATH)
        self.player = None
        self.item = None
        self.windows = []
        self.brand_windows = []
        self.status_item = None
        self.loop_observer = None
        self.focus_observer = None
        self.hud = None
        self.mouse_monitors = []
        self.hud_poll_timer = None
        self.last_hud_trigger = 0.0
        self.stats_timer = None
        self.last_battery_pct = 100
        self.tick = 0
        self.last_cpu_pct = "--"
        self.last_ram_gb = "--"
        self.hide_desktop_icons = False
        self.chat_window = None
        self.chat_webview = None
        return self

    def setup(self):
        self.setup_status_item()
        self.setup_focus_observer()
        self.setup_notch_hud()
        self.hide_desktop_icons = self.store.get_pref("hide_desktop_icons", False)
        self.apply_desktop_icons_policy()
        current = self.store.current()
        if current and Path(current).exists():
            self.load_video(current)
        self.start_stats_updates()

    def setup_status_item(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        icon = self.load_menu_icon()
        if icon is not None:
            button.setImage_(icon)
            button.setTitle_("")
        else:
            button.setTitle_("MW")
        self.rebuild_menu()

    def load_menu_icon(self):
        if MENU_ICON_SVG_PATH.exists():
            image = NSImage.alloc().initByReferencingFile_(str(MENU_ICON_SVG_PATH))
            if image is not None:
                image.setTemplate_(True)
                return image
        if MENU_ICON_PATH.exists():
            image = NSImage.alloc().initByReferencingFile_(str(MENU_ICON_PATH))
            if image is not None:
                image.setTemplate_(True)
                return image
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("video.fill", APP_NAME)
        if image is not None:
            image.setTemplate_(True)
        return image

    def rebuild_menu(self):
        menu = NSMenu.alloc().init()

        add_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Add MOV...", "onAddVideo:", "")
        add_item.setTarget_(self)
        menu.addItem_(add_item)

        reveal_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open Library Folder", "onOpenLibraryFolder:", "")
        reveal_item.setTarget_(self)
        menu.addItem_(reveal_item)

        menu.addItem_(NSMenuItem.separatorItem())

        lib = self.store.list_items()
        current = self.store.current()
        if current:
            now_playing = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"Now Playing: {Path(current).name}", None, "")
            now_playing.setEnabled_(False)
            menu.addItem_(now_playing)
            menu.addItem_(NSMenuItem.separatorItem())

        if not lib:
            empty = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Library empty", None, "")
            empty.setEnabled_(False)
            menu.addItem_(empty)
        else:
            for path in lib:
                title = Path(path).name
                if path == current:
                    title = f"✓ {title}"
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "onSelectVideo:", "")
                item.setTarget_(self)
                item.setRepresentedObject_(path)
                menu.addItem_(item)

            menu.addItem_(NSMenuItem.separatorItem())
            remove_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Remove Current", "onRemoveCurrent:", "")
            remove_item.setTarget_(self)
            remove_item.setEnabled_(self.store.current() is not None)
            menu.addItem_(remove_item)

        menu.addItem_(NSMenuItem.separatorItem())
        icons_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Hide Desktop Icons", "onToggleDesktopIcons:", ""
        )
        icons_item.setTarget_(self)
        icons_item.setState_(1 if self.hide_desktop_icons else 0)
        menu.addItem_(icons_item)

        menu.addItem_(NSMenuItem.separatorItem())
        is_playing = self.player is not None and self.player.rate() > 0
        toggle_title = "Pause" if is_playing else "Resume"
        toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(toggle_title, "onToggle:", "")
        toggle_item.setTarget_(self)
        toggle_item.setEnabled_(self.player is not None)
        menu.addItem_(toggle_item)

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "onQuit:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        self.status_item.setMenu_(menu)

    def setup_focus_observer(self):
        self.focus_observer = FocusObserver.alloc().initWithController_(self)
        ws_center = NSWorkspace.sharedWorkspace().notificationCenter()
        ws_center.addObserver_selector_name_object_(
            self.focus_observer,
            "appDidActivate:",
            NSWorkspaceDidActivateApplicationNotification,
            None,
        )

    def setup_notch_hud(self):
        self.hud = NotchHUD(self)
        self.hud_poll_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "pollMouseForHUD:", None, True
        )

    def pollMouseForHUD_(self, _timer):
        import time
        loc = NSEvent.mouseLocation()
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        f = screen.frame()
        top_band = f.origin.y + f.size.height - 28
        center_x = f.origin.x + f.size.width / 2
        in_zone = loc.y >= top_band and abs(loc.x - center_x) <= 180
        now = time.time()
        if in_zone and now - self.last_hud_trigger > 1.0:
            self.last_hud_trigger = now
            self.hud.show_temporarily()

    def should_play_now(self):
        # Power-aware playback policy:
        # - Below 25% battery: play only when Finder/Desktop is frontmost.
        # - Otherwise keep always-on playback.
        if self.last_battery_pct < 25:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return False
            bid = app.bundleIdentifier() or ""
            return bid == "com.apple.finder"
        return True

    def apply_play_policy(self):
        if self.player is None:
            return
        if self.should_play_now():
            self.player.play()
        else:
            self.player.pause()

    def clear_windows(self):
        for w in self.windows:
            w.window.orderOut_(None)
        self.windows = []
        for w in self.brand_windows:
            w.window.orderOut_(None)
        self.brand_windows = []

    def build_windows(self):
        self.clear_windows()
        if self.player is None:
            return
        for screen in NSScreen.screens():
            self.windows.append(WallpaperWindow(screen, self.player))
            self.brand_windows.append(BrandOverlayWindow(screen, self))

    def load_video(self, path):
        p = Path(path)
        if not p.exists() or not p.is_file():
            return
        url = NSURL.fileURLWithPath_(str(p.resolve()))
        item = AVPlayerItem.playerItemWithURL_(url)
        self.item = item
        self.player = AVPlayer.alloc().initWithPlayerItem_(item)

        self.loop_observer = LoopObserver.alloc().initWithController_(self)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.loop_observer,
            "playerItemDidReachEnd:",
            AVPlayerItemDidPlayToEndTimeNotification,
            item,
        )

        self.store.set_current(str(p.resolve()))
        self.build_windows()
        self.apply_play_policy()
        self.rebuild_menu()

    def onAddVideo_(self, _sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["mov", "mp4", "m4v"])  # library-friendly
        if panel.runModal() == 1:
            url = panel.URL()
            if url is not None:
                path = str(url.path())
                self.store.add(path)
                self.load_video(path)

    def onSelectVideo_(self, sender):
        path = sender.representedObject()
        if path:
            self.load_video(path)

    def onRemoveCurrent_(self, _sender):
        current = self.store.current()
        if current is None:
            return
        self.store.remove(current)
        next_current = self.store.current()
        if next_current and Path(next_current).exists():
            self.load_video(next_current)
        else:
            if self.player is not None:
                self.player.pause()
            self.player = None
            self.item = None
            self.clear_windows()
            self.rebuild_menu()

    def onOpenLibraryFolder_(self, _sender):
        APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(APP_SUPPORT_DIR)))

    def onToggle_(self, _sender):
        if self.player is None:
            return
        rate = self.player.rate()
        if rate > 0:
            self.player.pause()
        else:
            self.apply_play_policy()
        self.rebuild_menu()

    def onQuit_(self, _sender):
        self.show_desktop_icons()
        NSApp.terminate_(None)

    def onHUDPause_(self, _sender):
        if self.player is not None:
            self.player.pause()
        self.rebuild_menu()

    def onHUDContinue_(self, _sender):
        if self.player is not None:
            self.player.play()
        self.rebuild_menu()

    def apply_desktop_icons_policy(self):
        if self.hide_desktop_icons:
            self.hide_desktop_icons_now()
        else:
            self.show_desktop_icons()

    def hide_desktop_icons_now(self):
        subprocess.run(
            ["defaults", "write", "com.apple.finder", "CreateDesktop", "-bool", "false"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["killall", "Finder"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def show_desktop_icons(self):
        subprocess.run(
            ["defaults", "write", "com.apple.finder", "CreateDesktop", "-bool", "true"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["killall", "Finder"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def onToggleDesktopIcons_(self, _sender):
        self.hide_desktop_icons = not self.hide_desktop_icons
        self.store.set_pref("hide_desktop_icons", self.hide_desktop_icons)
        self.apply_desktop_icons_policy()
        self.rebuild_menu()

    def get_battery_percent(self):
        try:
            out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
            for part in out.split():
                if part.endswith("%;") or part.endswith("%"):
                    return int(part.replace("%;", "").replace("%", ""))
            return 0
        except Exception:
            return 0

    def get_ram_used_gb(self):
        try:
            out = subprocess.check_output(["vm_stat"], text=True)
            page_size = 4096
            total_pages = 0
            free_pages = 0
            for line in out.splitlines():
                if "page size of" in line:
                    page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
                if ":" in line:
                    k, v = line.split(":", 1)
                    n = int(v.strip().replace(".", ""))
                    if "Pages free" in k:
                        free_pages = n
                    if any(x in k for x in ["Pages free", "Pages active", "Pages inactive", "Pages speculative", "Pages wired down", "Pages occupied by compressor"]):
                        total_pages += n
            used = max(total_pages - free_pages, 0) * page_size
            return f"{used / (1024**3):.1f}"
        except Exception:
            return "--"

    def get_cpu_percent(self):
        try:
            load = os.getloadavg()[0]
            cpu_count = os.cpu_count() or 8
            pct = int(min(100, max(0, round((load / cpu_count) * 100))))
            return str(pct)
        except Exception:
            return "--"

    def get_now_playing(self):
        # Prefer Spotify, fallback to Music.app
        spotify_script = """
        if application "Spotify" is running then
          tell application "Spotify"
            if player state is playing then
              set t to name of current track
              set a to artist of current track
              set d to duration of current track
              set p to player position
              set u to artwork url of current track
              return t & "||" & a & "||" & (p as text) & "||" & (d as text) & "||" & u
            end if
          end tell
        end if
        return ""
        """
        music_script = """
        if application "Music" is running then
          tell application "Music"
            if player state is playing then
              set t to name of current track
              set a to artist of current track
              set d to duration of current track
              set p to player position
              return t & "||" & a & "||" & (p as text) & "||" & (d as text) & "||"
            end if
          end tell
        end if
        return ""
        """
        try:
            out = subprocess.check_output(["osascript", "-e", spotify_script], text=True).strip()
            if not out:
                out = subprocess.check_output(["osascript", "-e", music_script], text=True).strip()
            if not out:
                return ("", "", "", "")
            t, a, p, d, u = (out.split("||") + ["", "", "", "", ""])[:5]
            p_i = max(0, int(float((p or "0").replace(",", "."))))
            d_raw = float((d or "0").replace(",", "."))
            d_i = max(0, int(d_raw / 1000 if d_raw > 1000 else d_raw))
            return (t, a, f"{p_i//60:02d}:{p_i%60:02d}/{d_i//60:02d}:{d_i%60:02d}", u)
        except Exception:
            return ("", "", "", "")

    def start_stats_updates(self):
        self.stats_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            8.0, self, "updateOverlayStats:", None, True
        )
        self.updateOverlayStats_(None)

    def updateOverlayStats_(self, _timer):
        self.tick += 1
        b = self.get_battery_percent()
        self.last_battery_pct = b
        if self.tick % 2 == 0:
            self.last_cpu_pct = self.get_cpu_percent()
            self.last_ram_gb = self.get_ram_used_gb()
        c = self.last_cpu_pct
        r = self.last_ram_gb
        # Poll now-playing less frequently to reduce AppleScript overhead.
        if self.tick % 4 == 0:
            t, a, tt, u = self.get_now_playing()
            self._np_cache = (t, a, tt, u)
        else:
            t, a, tt, u = getattr(self, "_np_cache", ("", "", "", ""))
        self.apply_play_policy()
        for w in self.brand_windows:
            w.update_stats(b, c, r)
            w.update_now_playing(t, a, tt, u)


    def webView_decidePolicyForNavigationAction_decisionHandler_(self, _webview, nav_action, decision_handler):
        req = nav_action.request()
        url = req.URL()
        try:
            scheme = str(url.scheme()) if url is not None else ""
            host = str(url.host()) if url is not None else ""
        except Exception:
            scheme, host = "", ""
        if scheme == "movwall" and host == "open-chat":
            self.open_chat_window()
            decision_handler(0)
            return
        if scheme == "movwall" and host == "ask":
            query = str(url.query() or "") if url is not None else ""
            q = urllib.parse.parse_qs(query).get("q", [""])[0]
            self.handle_chat_prompt(q)
            decision_handler(0)
            return
        if scheme == "movwall" and host == "close-chat":
            if self.chat_window is not None:
                self.chat_window.close()
                self.chat_window = None
                self.chat_webview = None
            decision_handler(0)
            return
        decision_handler(1)

    def handle_chat_prompt(self, prompt):
        def worker():
            answer = "Unable to reach model endpoint."
            try:
                payload = {
                    "model": "qwen2.5-coder:1.5b",
                    "prompt": f"You are MovWall support assistant. Keep replies concise and practical. User question: {prompt}",
                    "stream": False,
                }
                req = urllib.request.Request(
                    "http://167.86.75.158:11434/api/generate",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    answer = (data.get("response") or answer).strip()
            except Exception:
                pass
            if self.chat_webview is not None:
                safe = answer.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
                self.chat_webview.evaluateJavaScript_completionHandler_(
                    f"window.__pushAI && window.__pushAI('{safe}');", None
                )
        threading.Thread(target=worker, daemon=True).start()

    def open_chat_window(self):
        if self.chat_window is not None:
            self.chat_window.makeKeyAndOrderFront_(None)
            return
        rect = ((260, 180), (560, 420))
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled,
            NSBackingStoreBuffered,
            False,
        )
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.92))
        win.setHasShadow_(True)
        win.setMovableByWindowBackground_(True)
        cfg = WKWebViewConfiguration.alloc().init()
        chat = WKWebView.alloc().initWithFrame_configuration_(((0, 0), (560, 420)), cfg)
        chat.setNavigationDelegate_(self)
        chat.setOpaque_(False)
        chat_html = """
        <html><head><meta charset="utf-8" />
        <style>
        body{margin:0;background:#0f1115;color:#fff;font:13px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
        #wrap{padding:0}
        #bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:0;padding:10px 12px}
        #close{border:1px solid rgba(255,255,255,.18);background:#1a1d24;color:#fff;border-radius:8px;padding:6px 10px;cursor:pointer}
        #content{padding:12px}
        #log{height:300px;overflow:hidden;background:#121317;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px}
        #in{width:100%;margin-top:10px;border:1px solid rgba(255,255,255,.18);background:#171a20;color:#fff;border-radius:8px;padding:10px;outline:none}
        .m{margin:6px 0}
        .m:last-child{margin-bottom:0}
        </style></head><body><div id="wrap">
          <div id="bar"><b>ML Helper</b><button id="close">Close</button></div>
          <div id="content">
          <div id="log"><div class="m"><b>AI:</b> ML Helper ready.</div></div>
          <input id="in" placeholder="Ask about your system..." />
          </div>
        </div>
        <script>
        const input=document.getElementById('in'), log=document.getElementById('log');
        document.getElementById('close').addEventListener('click', ()=>{ window.location.href='movwall://close-chat'; });
        window.__pushAI = function(text){
          const t=document.getElementById('typing'); if(t) t.remove();
          log.insertAdjacentHTML('beforeend',`<div class="m"><b>AI:</b> ${String(text).replace(/</g,'&lt;')}</div>`);
          log.scrollTop=log.scrollHeight;
        };
        input.addEventListener('keydown', async (e)=>{ if(e.key!=='Enter') return; const q=input.value.trim(); if(!q) return;
          log.insertAdjacentHTML('beforeend',`<div class=\"m\"><b>You:</b> ${q}</div><div class=\"m\" id=\"typing\"><b>AI:</b> Thinking...</div>`);
          log.scrollTop=log.scrollHeight; input.value='';
          window.location.href = 'movwall://ask?q=' + encodeURIComponent(q);
        });
        </script></body></html>
        """
        chat.loadHTMLString_baseURL_(chat_html, None)
        win.setContentView_(chat)
        win.makeKeyAndOrderFront_(None)
        self.chat_window = win
        self.chat_webview = chat


def validate_video_path(path):
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadi: {path}")
    if not p.is_file():
        raise ValueError(f"Gecersiz dosya: {path}")
    return str(p)


def main():
    if sys.platform != "darwin":
        print("MovWall currently ships full desktop features on macOS. Linux support uses a lightweight fallback mode.")
        return

    parser = argparse.ArgumentParser(description="macOS menubar animated wallpaper daemon")
    parser.add_argument("video", nargs="?", help="Baslangic videosu (.mov)")
    args = parser.parse_args()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    controller = AppController.alloc().init()
    controller.setup()

    if args.video:
        path = validate_video_path(args.video)
        controller.store.add(path)
        controller.load_video(path)

    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        sys.exit(1)
