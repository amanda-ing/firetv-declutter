# firetv-declutter

Make an Amazon Fire TV faster and quieter from your **Mac or Windows PC**: turn off Amazon's ads,
tracking and telemetry, and swap the ad-filled home screen for a clean one with
a dock of your favourite apps and rotating nature wallpapers.

Everything is **reversible**. Apps are disabled, never uninstalled, and every
change is recorded so one double-click puts the TV back exactly as it was.

> **Testing status:** tested on a real Toshiba 55C350LU (Fire OS 7.7.1.7) from
> Windows 11, with a dry run and then a full run. Every step was also first done
> by hand on that TV from a Mac and checked with screenshots. On this model
> Amazon protects four packages (ad deep-linking, device metrics, crash and log
> managers), so the tool reports and skips them. Other Fire OS 7 TVs and sticks
> should work. Fire OS 6/8 may work. Try `--dry-run` first on a new device.
> **Vega OS devices are not supported** (they aren't Android). Use at your own risk.

## What it does

1. Finds your Fire TV on your Wi-Fi and connects over ADB.
2. Backs up the TV's app list and settings before changing anything.
3. Offers the **Recommended preset** or lets you **Customize** group by group.
4. Disables the chosen Amazon services and applies privacy settings.
5. Installs [Projectivy Launcher](https://github.com/spocky/miproja1) (official
   GitHub release) and turns on its Home-button takeover.
6. Takes TV screenshots before and after, and writes a full log.

### Recommended preset

| Turned off | Left alone (Customize to turn off) |
|---|---|
| Ads and viewing tracking (ad ID, content recognition) | Alexa voice |
| Telemetry, metrics and log uploaders | Screen mirroring (Miracast) |
| Autoplay previews, demo content, tutorials | Smart home, Matter, video calls |
| Amazon shopping | Amazon Music and Photos |
| Games hub | Amazon Kids |
| miniTV | Silk browser |

Plus: limit ad tracking on, interest-based ads off, usage-data collection off,
content recognition off, and faster (0.5x) animations.

**Never touched:** AirPlay, Live TV, HDMI inputs, the Appstore, Fire OS updates,
the keyboard, Wi-Fi/Bluetooth, Prime Video and every app you installed.

The full list, with a comment on each package, is in [`debloat.conf`](debloat.conf).
A few packages (ad deep-linking, device metrics, crash and log managers) are
protected by Amazon on some models; the tool reports and skips them.

## Before you start

On the Fire TV:

1. **Settings > My Fire TV > About**: select the device name 7 times to unlock
   Developer Options (skip if you already see Developer Options).
2. **Settings > My Fire TV > Developer Options**: turn on **ADB debugging**.

On your computer:

- **Python 3.8 or newer.**
  - **Mac:** open Terminal and type `python3 --version`. If macOS offers to
    install developer tools, accept. Or install from
    [python.org](https://www.python.org/downloads/).
  - **Windows:** install from [python.org](https://www.python.org/downloads/)
    and tick **Add python.exe to PATH**, or get Python from the Microsoft Store.
- Be on the same network as the TV. Work or school computers may block scripts
  or local-network access. If so, use a personal computer.

Nothing else is needed. The tool uses only Python's built-in libraries and
downloads Google's ADB tools for your system on first run.

## Run it

1. Download this repo (green **Code** button > **Download ZIP**) and unzip it.
2. Double-click **Start Here.command** (Mac) or **Start Here.bat** (Windows).
   - **Mac:** if it can't be opened, right-click it, choose **Open**, then
     **Open** again. If asked to let Terminal find devices on your local
     network, choose **Allow**.
   - **Windows:** if SmartScreen warns you, choose **More info** > **Run
     anyway**. If Windows Firewall asks about Python, allow **Private networks**.
3. On the TV, when asked **Allow USB debugging?**, tick **Always allow from this
   computer** and choose **OK**.
4. Choose the Recommended preset or Customize.
5. Finish the home screen on the TV with the remote (the tool prints these steps):
   - Click through Projectivy's welcome screens. Allow TV listings if you use
     Live TV, and answer **No** to anonymous usage reporting.
   - **Make your dock:** Menu button (three lines) > **Edit categories** >
     **New category**. Set **Title** to `Favorites` (on the keyboard choose
     **Next**), then **Manage apps** and switch on your favourite apps in the
     order you want them. Press Back until you're home.
   - **Menu > Projectivy settings > General**: make sure both anonymous
     usage/crash reports are off.

Pressing Home may show Amazon's screen for a moment before Projectivy takes
over. That's a Fire TV limitation, and it's normal.

Command-line options:

```
python3 firetv_declutter.py                 # interactive  (Windows: py -3 firetv_declutter.py)
python3 firetv_declutter.py --ip 192.168.1.50
python3 firetv_declutter.py --dry-run       # show what would change
python3 firetv_declutter.py --yes           # Recommended preset, no questions
python3 firetv_declutter.py --restore       # undo everything
```

## Undo

Double-click **Restore.command** (Mac) or **Restore.bat** (Windows), then restart the TV
(**Settings > My Fire TV > Restart**). It turns every disabled app back on,
resets every changed setting to its old value, switches off the Home-button
takeover, and offers to uninstall Projectivy.

Restore relies on the `tvs/` folder this tool creates next to it, so keep
that folder. You can also turn apps back on by hand in
**Settings > Applications > Manage Installed Applications**.

## Files it creates

```
platform-tools/            Google's ADB tools for your OS (downloaded on first run)
tvs/<serial>/
  backup-original/         snapshot from the very first run
  backup-<date>/           snapshot from each run
  changes/                 exactly what was changed (used by Restore)
  screens/                 TV screenshots
  firetv-declutter.log     everything that happened
```

`tvs/` is in `.gitignore`. It holds details about your TV, so don't commit it.

## If a Fire OS update undoes the home screen

Amazon updates sometimes turn accessibility services off. Run
**Start Here** again (already-done steps are skipped), or turn
Projectivy back on in **Settings > Accessibility**.

## Development

```
python3 tests/run_tests.py
```

This runs the whole flow against a simulated TV (`tests/fake_adb.py`) on any
OS: Recommended run, re-run, Customize (with an existing accessibility service),
restore, dry run (including on an already set-up TV), and refusing non-Fire OS
devices. It works in a temporary
copy, so nothing is left behind. The GitHub download of Projectivy and real
network scanning aren't exercised.

The code is a single file, `firetv_declutter.py`, with no third-party
dependencies. Package groups live in `debloat.conf`.

## Credits

- [Projectivy Launcher](https://github.com/spocky/miproja1) by spocky (free, with an optional premium tier).
- Android platform-tools by Google.

Not affiliated with Amazon, Toshiba or Projectivy.
