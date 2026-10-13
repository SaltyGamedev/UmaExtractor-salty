# UmaExtractor (Salty's Linux fork)

**Repository:** https://github.com/SaltyGamedev/UmaExtractor-salty

Dump your veteran Uma Musume character list (stats, skills, aptitudes and inheritance factors/sparks) into a JSON file you can load into web tools for filtering and breeding.

This fork adds a small **Linux desktop app**, so on Steam/Proton you don't have to use the terminal or `sudo`.

## Features

- **Desktop app (GTK):** a small window, no command line needed
- **Live process detection:** shows the game process it attaches to (`UmamusumePrettyDerby.exe` and its PID) and refreshes every 2 seconds
- **One-click extraction:** scans the game's memory in the background and shows a spinner and a log
- **Timestamped exports:** each extraction is saved automatically as a new file, so older exports are kept
- **No root in most cases:** Wine lets your own user read the game's memory. If your system blocks this, the app asks for your password through `pkexec`.
- **Privacy:** `viewer_id` and `owner_viewer_id` are removed before saving
- **Menu and desktop launcher:** launch it like any other app
- **Read-only:** the app only reads memory and never modifies the game

## Install (Linux)

Requirements: Python 3.10+, GTK 3 bindings (PyGObject) and `msgpack`. On Debian, Ubuntu or Linux Mint:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-msgpack
git clone https://github.com/SaltyGamedev/UmaExtractor-salty.git
cd UmaExtractor-salty
python3 py/linux_gui.py --install-launcher
```

The last command adds **UmaExtractor** to your application menu and puts a shortcut with the logo on your desktop. If you move the folder later, run it again.

## Usage

1. Launch **Uma Musume Pretty Derby** through Steam.
2. In the game, open **Enhance → List** (Veteran List) and wait for it to load.
3. Open **UmaExtractor** from the menu or desktop. The *Game process* box should show `UmamusumePrettyDerby.exe` with its PID.
4. Click **Extract**. The scan takes about 30–60 seconds.
5. When it finishes, the file name is shown. Click **Open exports folder** to see it.

Don't start the app with `sudo`. If extraction says *No veteran data found*, make sure the Veteran List is open and fully loaded, then try again.

### Command line (optional)

The original script still works and writes `data.json` to the current folder:

```bash
python3 py/linux_extract.py        # add sudo only if you get "Permission denied"
```

## Output

**Changed in this fork:** the desktop app saves to `exports/data_<YYYY-MM-DD_HH-MM-SS>.json` in the project folder instead of a single `data.json`. Each run creates a new file, and `exports/` is ignored by git. The command-line script still writes `data.json`.

Each file contains a JSON array with one object per veteran character, including:

- `card_id`, `chara_id`: character identifiers
- `speed`, `stamina`, `power`, `guts`, `wiz`: stats
- `factor_id_array`: inheritance factors (sparks)
- `skill_array`: learned skills
- `proper_distance_*`, `proper_ground_*`: aptitudes
- and many more fields

`viewer_id` and `owner_viewer_id` are removed. A sample `data.json` is included in the project root.

## Is this bannable?

The tool only reads game memory and doesn't modify anything. The game currently has no anti-cheat that detects memory reading. Use at your own discretion.

## Credits

This fork builds on the work of others:

- **umadump**: the original concept and implementation
- **[xancia/UmaExtractor](https://github.com/xancia/UmaExtractor)**: the updated fork with the resilient memory scan that this fork is based on, including the Windows executable and the Frida script. Thanks to xancia (Cuong Ma), Ivan Nikitin, wugerworks (Linux extraction fixes), cBachoo and the other contributors.
- **SaltyGamedev**: the Linux desktop app, launcher and timestamped exports in this fork

Windows users should use the upstream [xancia/UmaExtractor](https://github.com/xancia/UmaExtractor) release.
