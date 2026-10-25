#!/usr/bin/env python3
"""firetv-declutter: reversible Fire TV cleanup for macOS, Windows and Linux.

Debloats an Amazon Fire TV running Fire OS over Wi-Fi ADB and optionally
installs the Projectivy home screen. Every change is recorded so it can be
undone with --restore.

Usage:
  python3 firetv_declutter.py                  interactive (recommended preset or customize)
  python3 firetv_declutter.py --ip 192.168.1.50
  python3 firetv_declutter.py --dry-run        show what would change, change nothing
  python3 firetv_declutter.py --restore        undo everything this tool changed
  python3 firetv_declutter.py --yes            accept the Recommended preset without questions

Only the Python standard library is used (Python 3.8+).
Environment (mainly for testing): ADB=path/to/adb (a .py file is run with Python),
FIRETV_IP, ASSUME_DEFAULTS=1, FIRETV_ANSWERS="n y y ...", FIRETV_TEST_APK=path.
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
CONF = HERE / "debloat.conf"
STATE_ROOT = HERE / "tvs"
PT_DIR = HERE / "platform-tools"

PROJECTIVY_PKG = "com.spocky.projengmenu"
PROJECTIVY_SVC_DEFAULT = "com.spocky.projengmenu/com.spocky.projengmenu.services.ProjectivyAccessibilityService"
PROJECTIVY_API = os.environ.get("PROJECTIVY_API", "https://api.github.com/repos/spocky/miproja1/releases/latest")
PROJECTIVY_URL_PREFIX = "https://github.com/spocky/miproja1/releases/download/"

PRIVACY_SETTINGS = [
    ("secure", "limit_ad_tracking", "1"),
    ("secure", "amz_limit_ad_tracking", "1"),
    ("secure", "non_amz_limit_ad_tracking", "1"),
    ("secure", "advertisingIdApp:interestBasedAds:value", "0"),
    ("secure", "pact_usage_collection_enabled", "0"),
    ("secure", "setting.com.amazon.tv.acr.enabled", "0"),
]
SPEED_SETTINGS = [
    ("global", "window_animation_scale", "0.5"),
    ("global", "transition_animation_scale", "0.5"),
    ("global", "animator_duration_scale", "0.5"),
]

FINISH_TEXT = """
FINISH THE HOME SCREEN ON THE TV (with the remote):
  1. Click through Projectivy's welcome screens. Allow the TV listings permission if you
     use Live TV. Answer No to anonymous usage reporting.
  2. Make your dock: press Menu (the button with three lines) > Edit categories >
     New category. Set Title to "Favorites" (on the keyboard, choose Next to confirm),
     then scroll down to Manage apps and switch on your favourite apps in the order
     you want them. Press Back until you're home: the new row sits at the top.
  3. Check privacy: Menu > Projectivy settings > General > turn off "Enable anonymous
     usage reports" and "Enable anonymous crash reports".
  Pressing Home may show Amazon's screen for a moment before Projectivy takes over.
  That's normal on Fire TV."""


class Stop(Exception):
    """Raised to stop the tool with a message for the user."""


class Tool:
    def __init__(self, args):
        self.args = args
        self.dry = args.dry_run
        self.yes = args.yes or os.environ.get("ASSUME_DEFAULTS") == "1"
        self.answers = os.environ.get("FIRETV_ANSWERS", "").split()
        self.ip = args.ip or os.environ.get("FIRETV_IP", "")
        self.adb_cmd = None
        self.tv = ""
        self.state = None
        self.log = None

    # ---------- output and questions ----------
    def say(self, text=""):
        print(text, flush=True)
        if self.log:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    def hr(self):
        self.say("-" * 60)

    def ask(self, question, default):
        hint = "[Y/n]" if default == "y" else "[y/N]"
        if self.answers:
            a = self.answers.pop(0)
            if a == "-":
                a = default
            self.say(f"{question} {hint} -> {a}")
            return a.lower().startswith("y")
        if self.yes:
            self.say(f"{question} {hint} -> {default} (default)")
            return default == "y"
        try:
            a = input(f"{question} {hint} ").strip()
        except EOFError:
            a = ""
        a = a or default
        if self.log:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(f"{question} {hint} -> {a}\n")
        return a.lower().startswith("y")

    def prompt(self, text):
        try:
            return input(text).strip()
        except EOFError:
            return ""

    # ---------- adb ----------
    def adb(self, *args, binary=False, timeout=120):
        """Run adb; return stdout (str, CR stripped) or bytes. Never raises."""
        try:
            p = subprocess.run(self.adb_cmd + [str(a) for a in args], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            return b"" if binary else f"adb error: {e}"
        if binary:
            return p.stdout
        return p.stdout.decode("utf-8", "replace").replace("\r", "")

    def adbt(self, *args, **kw):
        return self.adb("-s", self.tv, *args, **kw)

    def sh(self, *args):
        return self.adbt("shell", *args)

    def sh1(self, *args):
        lines = self.sh(*args).strip().splitlines()
        return lines[0].strip() if lines else ""

    def packages(self, *flags):
        return {l.strip()[8:] for l in self.sh("pm", "list", "packages", *flags).splitlines()
                if l.strip().startswith("package:")}

    # ---------- setup ----------
    def ensure_adb(self):
        env = os.environ.get("ADB")
        if env and Path(env).exists():
            self.adb_cmd = [sys.executable, env] if env.endswith(".py") else [env]
            return
        exe = PT_DIR / ("adb.exe" if os.name == "nt" else "adb")
        if not exe.exists():
            system = {"Darwin": "darwin", "Windows": "windows"}.get(platform.system(), "linux")
            url = f"https://dl.google.com/android/repository/platform-tools-latest-{system}.zip"
            self.say("Downloading Google's official ADB tools (platform-tools)...")
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    data = r.read()
                zipfile.ZipFile(io.BytesIO(data)).extractall(HERE)
            except Exception as e:  # noqa: BLE001 - report any download/unzip problem
                raise Stop(f"Could not download platform-tools ({e}). Check your internet connection.")
            if os.name != "nt":  # zipfile drops the executable bit
                for f in PT_DIR.iterdir():
                    if f.is_file():
                        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not exe.exists():
            raise Stop("platform-tools did not unpack as expected.")
        self.adb_cmd = [str(exe)]

    def start_server(self):
        # Start adb's background server with no pipes attached. Otherwise, on Windows
        # especially, the long-lived server can inherit our output pipe and make the
        # first adb call hang.
        try:
            subprocess.run(self.adb_cmd + ["start-server"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            pass

    @staticmethod
    def my_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the LAN interface
            return s.getsockname()[0]
        except OSError:
            return ""
        finally:
            s.close()

    def scan(self):
        me = self.my_ip()
        if not me or me.startswith("127."):
            return []
        prefix = me.rsplit(".", 1)[0]
        self.say(f"Scanning {prefix}.1-254 for devices with ADB debugging on (a few seconds)...")

        def probe(ip):
            try:
                with socket.create_connection((ip, 5555), timeout=1):
                    return ip
            except OSError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            hits = [ip for ip in ex.map(probe, [f"{prefix}.{i}" for i in range(1, 255)]) if ip]
        return hits

    def state_ok(self, target):
        return self.adb("-s", target, "get-state").strip() == "device"

    def pick_ip(self):
        if self.ip:
            return
        last = STATE_ROOT / "last-ip.txt"
        if last.exists():
            cand = last.read_text().strip()
            self.say(f"Trying the TV used last time: {cand}")
            self.adb("connect", f"{cand}:5555")
            if self.state_ok(f"{cand}:5555"):
                self.ip = cand
                return
        found = self.scan()
        if len(found) == 1:
            self.ip = found[0]
            self.say(f"Found ADB on {self.ip}")
        elif len(found) > 1:
            self.say("Found more than one device with ADB on:")
            for i, ip in enumerate(found, 1):
                self.say(f"  {i}) {ip}")
            c = self.prompt("Which number is your Fire TV? ")
            if c.isdigit() and 1 <= int(c) <= len(found):
                self.ip = found[int(c) - 1]
        if not self.ip:
            self.say("No Fire TV found automatically.")
            self.say("(macOS: allow Terminal to find local network devices. Windows: allow Python through the firewall.)")
            self.ip = self.prompt("Type the TV's IP address (Settings > My Fire TV > About > Network): ")
        if not self.ip:
            raise Stop("No TV IP address.")

    def connect(self):
        self.tv = f"{self.ip}:5555"
        self.say("")
        self.say(">>> Look at the TV. If it asks 'Allow USB debugging?', tick 'Always allow from this computer' and choose OK.")
        self.adb("connect", self.tv)
        for _ in range(45):
            if self.state_ok(self.tv):
                break
            time.sleep(2)
            self.adb("connect", self.tv)
        else:
            raise Stop(f"Could not connect to {self.tv}. Check that ADB debugging is on "
                       "(Settings > My Fire TV > Developer Options) and accept the prompt on the TV, then run again.")
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        (STATE_ROOT / "last-ip.txt").write_text(self.ip)

    def check_device(self, mode):
        name = self.sh1("getprop", "ro.build.version.name")
        sdk = self.sh1("getprop", "ro.build.version.sdk")
        model = self.sh1("getprop", "ro.product.model")
        serial = re.sub(r"[^A-Za-z0-9_-]", "", self.sh1("getprop", "ro.serialno")) or self.ip.replace(".", "-")
        self.state = STATE_ROOT / serial
        for d in ("changes", "screens"):
            (self.state / d).mkdir(parents=True, exist_ok=True)
        self.log = self.state / "firetv-declutter.log"
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now()} {mode} (v{VERSION}, {platform.system()}) =====\n")
        self.say(f"TV: {model} | {name or 'unknown OS'} | Android SDK {sdk or '?'}")
        if "Fire OS" not in name:
            raise Stop(f"This doesn't look like Fire OS ('{name}'). Vega OS and other systems are not supported.")
        if "Fire OS 7" not in name:
            self.say("Note: tested on Fire OS 7. Your version should work, but take extra care.")

    def screenshot(self, name):
        png = self.adbt("exec-out", "screencap", "-p", binary=True)
        if png:
            dest = self.state / "screens" / f"{name}.png"
            dest.write_bytes(png)
            self.say(f"  screenshot: {dest}")

    # ---------- backup ----------
    def backup(self):
        b = self.state / ("backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        b.mkdir(parents=True, exist_ok=True)
        self.say(f"Backing up the TV's current state to {b} ...")
        dumps = {
            "getprop.txt": ("getprop",),
            "packages-all.txt": ("pm", "list", "packages", "-f", "-U"),
            "packages-system.txt": ("pm", "list", "packages", "-s"),
            "packages-user-installed.txt": ("pm", "list", "packages", "-3"),
            "packages-disabled.txt": ("pm", "list", "packages", "-d"),
            "packages-enabled.txt": ("pm", "list", "packages", "-e"),
            "settings-global.txt": ("settings", "list", "global"),
            "settings-secure.txt": ("settings", "list", "secure"),
            "settings-system.txt": ("settings", "list", "system"),
            "home-launcher.txt": ("cmd", "package", "resolve-activity", "--brief", "-a",
                                  "android.intent.action.MAIN", "-c", "android.intent.category.HOME"),
        }
        for fname, cmd in dumps.items():
            (b / fname).write_text(self.sh(*cmd), encoding="utf-8")
        orig = self.state / "backup-original"
        if not orig.exists():
            shutil.copytree(b, orig)
        n = len([l for l in (b / "packages-all.txt").read_text(encoding="utf-8").splitlines() if l.strip()])
        self.say(f"  {n} packages and all settings saved. Original backup: backup-original")
        self.screenshot("01-before")

    # ---------- plan ----------
    @staticmethod
    def load_groups():
        groups, cur = [], None
        for raw in CONF.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("@group"):
                _, gid, rec, title = line.split(None, 3)
                cur = {"id": gid, "rec": rec, "title": title.strip(), "packages": []}
                groups.append(cur)
            elif cur is not None:
                cur["packages"].append(line.split()[0])
        return groups

    def choose_plan(self, groups):
        plan = {"groups": [], "privacy": True, "speed": True, "launcher": True}
        self.hr()
        self.say("RECOMMENDED PRESET")
        self.say("  Turn off:")
        for g in groups:
            if g["rec"] == "disable":
                self.say(f"    - {g['title']}")
        self.say("  Leave alone:")
        for g in groups:
            if g["rec"] == "keep":
                self.say(f"    - {g['title']}")
        self.say("    - AirPlay, Live TV, HDMI inputs, the Appstore, updates and all your streaming apps (never touched)")
        self.say("  Also: privacy settings (limit ad tracking, no interest-based ads, no usage data),")
        self.say("        faster animations, and the Projectivy ad-free home screen.")
        self.hr()
        if self.ask("Use the recommended preset?", "y"):
            plan["groups"] = [g for g in groups if g["rec"] == "disable"]
            return plan
        self.say("Customize: answer yes to turn a group OFF.")
        for g in groups:
            if self.ask(f"Turn off: {g['title']}?", "y" if g["rec"] == "disable" else "n"):
                plan["groups"].append(g)
        plan["privacy"] = self.ask("Apply privacy settings (limit ad tracking, no interest-based ads, no usage data)?", "y")
        plan["speed"] = self.ask("Speed up menu animations (0.5x)?", "y")
        plan["launcher"] = self.ask("Install the Projectivy ad-free home screen?", "y")
        return plan

    # ---------- apply ----------
    def changes(self, name):
        return self.state / "changes" / name

    def append(self, name, text):
        with open(self.changes(name), "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def record_setting_before(self, ns, key, old):
        f = self.changes("settings-before.tsv")
        if f.exists() and any(l.startswith(f"{ns}\t{key}\t") for l in f.read_text(encoding="utf-8").splitlines()):
            return
        self.append("settings-before.tsv", f"{ns}\t{key}\t{old}")

    def apply_packages(self, plan):
        enabled = self.packages("-e")
        off = skipped = protected = 0
        self.say("")
        self.say("Turning off packages...")
        for g in plan["groups"]:
            for p in g["packages"]:
                if p not in enabled:
                    self.say(f"  skip  {p} (not on this TV or already off)")
                    skipped += 1
                    continue
                if self.dry:
                    self.say(f"  would turn off  {p}")
                    continue
                out = self.sh("pm", "disable-user", "--user", "0", p)
                if "disabled-user" in out:
                    self.say(f"  off   {p}")
                    self.append("disabled-by-tool.txt", p)
                    off += 1
                elif "protected" in out.lower():
                    self.say(f"  kept  {p} (Amazon protects this one)")
                    protected += 1
                else:
                    self.say(f"  FAIL  {p}: {out.strip().splitlines()[0] if out.strip() else '?'}")
        self.say(f"  {off} turned off, {protected} protected by Amazon, {skipped} not present.")

    def apply_settings(self, plan):
        todo = (PRIVACY_SETTINGS if plan["privacy"] else []) + (SPEED_SETTINGS if plan["speed"] else [])
        if not todo:
            return
        self.say("")
        self.say("Changing settings...")
        for ns, key, val in todo:
            old = self.sh1("settings", "get", ns, key)
            if self.dry:
                self.say(f"  would set {key}: {old} -> {val}")
                continue
            self.record_setting_before(ns, key, old)
            self.sh("settings", "put", ns, key, val)
            self.say(f"  {key}: {old} -> {self.sh1('settings', 'get', ns, key)}")

    def install_launcher(self, plan):
        if not plan["launcher"]:
            return
        self.say("")
        self.say("Installing the Projectivy home screen...")
        if self.dry:
            self.say("  would download the latest Projectivy release from GitHub and turn on its Home-button takeover")
            return
        apk = self.state / "projectivy.apk"
        if PROJECTIVY_PKG not in self.packages(PROJECTIVY_PKG):
            test_apk = os.environ.get("FIRETV_TEST_APK")
            if test_apk:
                shutil.copyfile(test_apk, apk)
            else:
                try:
                    req = urllib.request.Request(PROJECTIVY_API, headers={"User-Agent": "firetv-declutter"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        rel = json.load(r)
                    url = next((a["browser_download_url"] for a in rel.get("assets", [])
                                if a.get("browser_download_url", "").endswith(".apk")), "")
                except Exception:  # noqa: BLE001
                    url = ""
                if not url.startswith(PROJECTIVY_URL_PREFIX):
                    self.say("  Could not find the official Projectivy APK on GitHub; skipping the home screen.")
                    return
                self.say(f"  downloading {url}")
                try:
                    with urllib.request.urlopen(url, timeout=300) as r:
                        apk.write_bytes(r.read())
                except Exception:  # noqa: BLE001
                    self.say("  download failed; skipping.")
                    return
            self.say(f"  sha256 {hashlib.sha256(apk.read_bytes()).hexdigest()}")
            result = self.adbt("install", "-r", str(apk), timeout=600).strip().splitlines()
            self.say(f"  {result[-1] if result else ''}")
            if PROJECTIVY_PKG not in self.packages(PROJECTIVY_PKG):
                self.say("  install failed; skipping.")
                return
            self.append("installed-by-tool.txt", PROJECTIVY_PKG)
        else:
            self.say("  Projectivy is already installed.")
        m = re.search(re.escape(PROJECTIVY_PKG) + r"/[A-Za-z0-9_.]*AccessibilityService", self.sh("dumpsys", "package", PROJECTIVY_PKG))
        svc = m.group(0) if m else PROJECTIVY_SVC_DEFAULT
        if "/." in svc:
            svc = f"{PROJECTIVY_PKG}/{PROJECTIVY_PKG}{svc.split('/', 1)[1]}"
        before = self.sh1("settings", "get", "secure", "enabled_accessibility_services")
        if svc in before:
            self.say("  Home-button takeover already on.")
        else:
            if not self.changes("accessibility-before.txt").exists():
                self.changes("accessibility-before.txt").write_text(before + "\n", encoding="utf-8")
            new = svc if before in ("", "null") else f"{before}:{svc}"
            self.sh("settings", "put", "secure", "enabled_accessibility_services", new)
            self.record_setting_before("secure", "accessibility_enabled", self.sh1("settings", "get", "secure", "accessibility_enabled"))
            self.sh("settings", "put", "secure", "accessibility_enabled", "1")
            self.say("  Home-button takeover turned on (Projectivy accessibility service).")
        self.sh("monkey", "-p", PROJECTIVY_PKG, "-c", "android.intent.category.LEANBACK_LAUNCHER", "1")
        time.sleep(float(os.environ.get("FIRETV_WAIT", "5")))
        self.screenshot("02-projectivy")

    def finish(self, plan):
        if not self.dry:
            self.sh("input", "keyevent", "KEYCODE_HOME")
            time.sleep(float(os.environ.get("FIRETV_WAIT", "6")))
            self.screenshot("03-after")
        self.hr()
        if self.dry:
            self.say("DRY RUN finished. Nothing on the TV was changed.")
            return
        self.say(f"DONE. Everything changed is recorded in {self.state / 'changes'}")
        self.say("To undo it all: double-click Restore (or run with --restore).")
        if plan["launcher"]:
            self.say(FINISH_TEXT)

    # ---------- restore ----------
    def restore(self):
        c = self.state / "changes"
        actionable = ("accessibility-before.txt", "disabled-by-tool.txt", "settings-before.tsv")
        if not any((c / f).exists() for f in actionable):
            if (c / "installed-by-tool.txt").exists() and self.ask("Nothing left to restore. Uninstall Projectivy?", "n"):
                out = self.adbt("uninstall", PROJECTIVY_PKG).strip().splitlines()
                self.say(f"  {out[-1] if out else ''}")
                (c / "installed-by-tool.txt").rename(c / "installed-by-tool.removed.txt")
                return
            raise Stop(f"No recorded changes for this TV in {c}. Nothing to restore.")
        self.say("Restoring this TV to how it was before firetv-declutter...")
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        def retire(f):
            f.rename(f.with_name(f"{f.stem}.restored-{stamp}{f.suffix}"))

        n = 0
        abf = c / "accessibility-before.txt"
        if abf.exists():
            a = abf.read_text(encoding="utf-8").strip()
            if a in ("", "null"):
                self.sh("settings", "delete", "secure", "enabled_accessibility_services")
            else:
                self.sh("settings", "put", "secure", "enabled_accessibility_services", a)
            self.sh("am", "force-stop", PROJECTIVY_PKG)
            self.say("  Home-button takeover turned off.")
            retire(abf)
        dis = c / "disabled-by-tool.txt"
        if dis.exists():
            for p in sorted({l.strip() for l in dis.read_text(encoding="utf-8").splitlines() if l.strip()}):
                out = self.sh("pm", "enable", "--user", "0", p)
                if "enabled" in out:
                    self.say(f"  on    {p}")
                    n += 1
                else:
                    self.say(f"  FAIL  {p}: {out.strip()}")
            retire(dis)
        sb = c / "settings-before.tsv"
        if sb.exists():
            for line in sb.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t", 2)
                if len(parts) < 2:
                    continue
                ns, key = parts[0], parts[1]
                old = parts[2] if len(parts) > 2 else ""
                if old in ("", "null"):
                    self.sh("settings", "delete", ns, key)
                else:
                    self.sh("settings", "put", ns, key, old)
                self.say(f"  reset {key} -> {old}")
            retire(sb)
        inst = c / "installed-by-tool.txt"
        if inst.exists() and self.ask("Also uninstall Projectivy?", "n"):
            out = self.adbt("uninstall", PROJECTIVY_PKG).strip().splitlines()
            self.say(f"  {out[-1] if out else ''}")
            retire(inst)
        self.hr()
        self.say(f"Restored ({n} apps turned back on). Restart the TV to finish: Settings > My Fire TV > Restart.")

    # ---------- main ----------
    def run(self):
        print(f"firetv-declutter {VERSION} - reversible Fire TV cleanup")
        if not CONF.exists():
            raise Stop("debloat.conf is missing.")
        self.ensure_adb()
        self.start_server()
        self.pick_ip()
        self.connect()
        mode = "restore" if self.args.restore else "run"
        self.check_device(mode)
        if self.args.restore:
            self.restore()
            return
        if self.dry:
            self.say("DRY RUN: nothing will be changed.")
        self.backup()
        plan = self.choose_plan(self.load_groups())
        self.apply_packages(plan)
        self.apply_settings(plan)
        self.install_launcher(plan)
        self.finish(plan)


def main():
    ap = argparse.ArgumentParser(description="Reversible Fire TV cleanup (Fire OS only).")
    ap.add_argument("--ip", help="the TV's IP address (otherwise it is found automatically)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ap.add_argument("--restore", action="store_true", help="undo everything this tool changed")
    ap.add_argument("--yes", "-y", action="store_true", help="accept the Recommended preset without questions")
    ap.add_argument("--no-pause", action="store_true", help="don't wait for Enter before closing")
    ap.add_argument("--version", action="version", version=f"firetv-declutter {VERSION}")
    args = ap.parse_args()
    tool = Tool(args)
    code = 0
    try:
        tool.run()
    except Stop as e:
        tool.say("")
        tool.say(f"STOPPED: {e}")
        code = 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        code = 130
    if not (args.no_pause or tool.yes or os.environ.get("FIRETV_ANSWERS") is not None):
        try:
            input("Press Enter to close. ")
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
