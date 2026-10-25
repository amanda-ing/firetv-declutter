#!/usr/bin/env python3
"""Simulated Fire TV for tests. State lives in the folder named by $FAKE_TV_DIR."""
import os
import sys
from pathlib import Path

D = Path(os.environ["FAKE_TV_DIR"])
PROJ = "com.spocky.projengmenu"


def load(name):
    f = D / name
    return [l for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def save(name, lines):
    (D / name).write_text("".join(l + "\n" for l in lines))


def out(text):
    # Real adb shell output uses CRLF on some hosts; mimic that.
    sys.stdout.write(text.replace("\n", "\r\n") + "\r\n")


a = sys.argv[1:]
if a[:1] == ["-s"]:
    a = a[2:]
cmd = a[0] if a else ""

if cmd == "connect":
    out(f"connected to {a[1]}")
elif cmd == "get-state":
    out("device")
elif cmd == "exec-out":
    sys.stdout.buffer.write(b"\x89PNG fake")
elif cmd == "install":
    save("enabled", load("enabled") + [PROJ])
    out("Performing Streamed Install\nSuccess")
elif cmd == "uninstall":
    save("enabled", [p for p in load("enabled") if p != a[1]])
    out("Success")
elif cmd == "shell":
    sub, r = a[1], a[2:]
    if sub == "getprop":
        key = r[0] if r else ""
        out({
            "ro.build.version.name": os.environ.get("FAKE_OS", "Fire OS 7.7.1.7 (PS7717/5741)"),
            "ro.build.version.sdk": "28",
            "ro.product.model": "AFTFAKE",
            "ro.serialno": "FAKESERIAL123",
        }.get(key, "[ro.product.model]: [AFTFAKE]"))
    elif sub == "pm":
        op = r[0]
        if op == "list":
            mode, filt = "all", ""
            for x in r[2:]:
                if x == "-e":
                    mode = "e"
                elif x == "-d":
                    mode = "d"
                elif not x.startswith("-"):
                    filt = x
            src = {"e": load("enabled"), "d": load("disabled")}.get(mode, load("enabled") + load("disabled"))
            lines = [f"package:{p}" for p in src if filt in p]
            if lines:
                out("\n".join(lines))
        elif op == "disable-user":
            p = r[-1]
            if p in load("protected"):
                out(f"Security exception: Cannot disable a protected package: {p}")
            else:
                save("enabled", [x for x in load("enabled") if x != p])
                save("disabled", load("disabled") + [p])
                out(f"Package {p} new state: disabled-user")
        elif op == "enable":
            p = r[-1]
            save("disabled", [x for x in load("disabled") if x != p])
            save("enabled", load("enabled") + [p])
            out(f"Package {p} new state: enabled")
    elif sub == "settings":
        op, ns = r[0], r[1]
        name = f"settings-{ns}"
        cur = load(name)
        if op == "get":
            k = r[2]
            hit = next((l[len(k) + 1:] for l in cur if l.startswith(k + "=")), "null")
            out(hit)
        elif op == "put":
            k, v = r[2], r[3]
            save(name, [l for l in cur if not l.startswith(k + "=")] + [f"{k}={v}"])
        elif op == "delete":
            k = r[2]
            save(name, [l for l in cur if not l.startswith(k + "=")])
        elif op == "list":
            if cur:
                out("\n".join(cur))
    elif sub == "dumpsys":
        if r[:1] == ["package"] and PROJ in load("enabled"):
            out(f"        619eb5b {PROJ}/.services.ProjectivyAccessibilityService filter")
    elif sub == "cmd":
        out("com.amazon.tv.launcher/.ui.HomeActivity_vNext")
sys.exit(0)
