#!/usr/bin/env python3
"""End-to-end tests against a simulated TV. Works on macOS, Windows and Linux.

    python3 tests/run_tests.py

Runs in a temporary copy of the tool, so nothing is left in the repo.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAKE = Path(__file__).resolve().parent / "fake_adb.py"
PROTECTED = ["com.amazon.ftvads.deeplinking", "com.amazon.device.metrics",
             "com.amazon.device.crashmanager", "com.amazon.device.logmanager"]

results = []


def check(name, ok):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def main():
    work = Path(tempfile.mkdtemp(prefix="firetv-test-"))
    tv = work / "tv"
    app = work / "app"
    tv.mkdir()
    app.mkdir()
    for f in ("firetv_declutter.py", "debloat.conf"):
        shutil.copy(REPO / f, app / f)
    (work / "fake.apk").write_bytes(b"apk")

    def L(name):
        f = tv / name
        return [l for l in f.read_text().splitlines() if l.strip()] if f.exists() else []

    def W(name, lines):
        (tv / name).write_text("".join(l + "\n" for l in lines))

    def settings():
        return sorted(L("settings-secure") + L("settings-global"))

    env = dict(os.environ, FAKE_TV_DIR=str(tv), ADB=str(FAKE), FIRETV_IP="10.9.9.9",
               FIRETV_TEST_APK=str(work / "fake.apk"), FIRETV_WAIT="0")

    def run(*extra, answers=None, os_name=None):
        e = dict(env)
        if answers is None:
            e["ASSUME_DEFAULTS"] = "1"
        else:
            e["FIRETV_ANSWERS"] = answers
        if os_name:
            e["FAKE_OS"] = os_name
        p = subprocess.run([sys.executable, str(app / "firetv_declutter.py"), "--no-pause", *extra],
                           env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=120)
        return p.stdout.decode("utf-8", "replace")

    conf_pkgs = []
    for raw in (REPO / "debloat.conf").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("@"):
            conf_pkgs.append(line.split()[0])
    W("enabled", conf_pkgs + ["com.amazon.tv.launcher", "com.amazon.venezia", "com.netflix.ninja"])
    W("disabled", ["com.android.nfc"])
    W("protected", PROTECTED)
    W("settings-secure", ["limit_ad_tracking=0", "amz_limit_ad_tracking=0",
                          "advertisingIdApp:interestBasedAds:value=1", "setting.com.amazon.tv.acr.enabled=1"])
    W("settings-global", ["window_animation_scale=1.0", "transition_animation_scale=1.0"])
    orig = sorted(L("enabled"))
    orig_settings = settings()

    dry = run("--dry-run")
    check("dry run changes nothing", sorted(L("enabled")) == orig and settings() == orig_settings)
    m = re.search(r"(\d+) would be turned off", dry)
    check("dry run counts what it would turn off", bool(m) and int(m.group(1)) == dry.count("would turn off  "))
    check("dry run on a new TV would install Projectivy", "would download the latest Projectivy" in dry)

    out = run()
    en = set(L("enabled"))
    check("recommended groups off", not en & {"com.amazon.tv.acr", "com.amazon.sneakpeek", "com.amazon.gamehub",
                                               "com.amazon.shoptv.client", "com.amazon.minitv.android.app"})
    check("keep-groups untouched", {"com.amazon.vizzini", "com.amazon.tahoe", "com.amazon.cloud9", "com.amazon.cast.sink"} <= en)
    check("never-touch apps still on", {"com.amazon.tv.launcher", "com.amazon.venezia", "com.netflix.ninja"} <= en)
    check("protected packages reported, not fatal", "Amazon protects" in out and set(PROTECTED) <= en)
    check("privacy settings applied", "limit_ad_tracking=1" in L("settings-secure")
          and "setting.com.amazon.tv.acr.enabled=0" in L("settings-secure"))
    check("animations sped up", "animator_duration_scale=0.5" in L("settings-global"))
    check("backup written", (app / "tvs" / "FAKESERIAL123" / "backup-original" / "packages-all.txt").exists())
    check("screenshots saved", (app / "tvs" / "FAKESERIAL123" / "screens" / "03-after.png").exists())
    check("home-button takeover on", any("ProjectivyAccessibilityService" in l for l in L("settings-secure")))

    check("first run shows home-screen steps", "FINISH THE HOME SCREEN" in out)

    out2 = run()
    check("second run makes no new changes", "0 turned off" in out2)
    check("second run reports settings already set", "already set  limit_ad_tracking: 1" in out2
          and "1 -> 1" not in out2)
    check("second run skips home-screen steps", "FINISH THE HOME SCREEN" not in out2
          and "nothing to finish" in out2)

    dry2 = run("--dry-run")
    check("dry run sees Projectivy already set up", "Projectivy is already installed" in dry2
          and "Home-button takeover already on" in dry2 and "would download" not in dry2)

    run("--restore")
    check("restore re-enables everything", sorted(p for p in L("enabled") if p != "com.spocky.projengmenu") == orig)
    check("restore resets settings", settings() == orig_settings)

    # Customize path, with another accessibility service already enabled
    W("settings-secure", L("settings-secure") + ["enabled_accessibility_services=com.other.app/.Svc"])
    orig_settings = settings()
    # preset n | ads y telemetry y autoplay n shopping n games n minitv n alexa y mirroring n
    #            smarthome n musicphotos n kids n silk y | privacy n | speed n | launcher y
    run(answers="n y y n n n n y n n n n y n n y")
    en = set(L("enabled"))
    check("customize: chosen groups off", not en & {"com.amazon.vizzini", "com.amazon.cloud9", "com.amazon.tv.acr"})
    check("customize: unchosen groups on", {"com.amazon.sneakpeek", "com.amazon.gamehub"} <= en)
    check("customize: privacy skipped", "limit_ad_tracking=0" in L("settings-secure"))
    check("existing accessibility service kept", any(l.startswith("enabled_accessibility_services=com.other.app/.Svc:com.spocky")
                                                     for l in L("settings-secure")))
    run("--restore")
    check("restore after customize", sorted(p for p in L("enabled") if p != "com.spocky.projengmenu") == orig
          and settings() == orig_settings)

    out3 = run("--restore")
    check("restore with nothing to do stops cleanly", "Nothing to restore" in out3)

    vega = run(os_name="VegaOS 1.1")
    check("refuses non-Fire OS", "not supported" in vega)

    shutil.rmtree(work, ignore_errors=True)
    if all(results):
        print(f"ALL {len(results)} TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
