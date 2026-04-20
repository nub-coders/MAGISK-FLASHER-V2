# Magisk Boot Patcher

Patch a stock `boot.img` with any Magisk version — run it interactively on your local machine, pass CLI arguments for scripting, or deploy it as a Telegram bot.

Magisk versions are fetched **live from GitHub Releases** — no APK files need to be bundled.

---

## Features

- 🖥️ **Interactive CLI** — menu-driven local patching
- ⚙️ **CLI arguments** — fully scriptable / non-interactive
- 🤖 **Telegram Bot** — users send `boot.img`, pick a version, get back a patched image
- 🌐 **Live version list** — always up-to-date: 5 Official + 5 Delta + 5 Alpha builds

---

## Requirements

```
Python 3.10+
unzip  (system package)
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

> **Bot mode only** requires `telethon`, `FastTelethonhelper`, `tgcrypto`, `cryptg`.  
> Local CLI mode works with **zero extra dependencies** beyond the Python standard library.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/ankitkr88588/MAGISK-FLASHER-V2
cd MAGISK-FLASHER-V2
```

### 2. Edit `config.py`

```python
API_ID       = 123456          # from my.telegram.org
API_HASH     = 'your_hash'
BOT_TOKEN    = 'your_bot_token'
```

---

## Usage

### Interactive menu (no arguments)

```bash
python3 main.py
```

```
  MAGISK FLASHER v2
  ════════════════════════════════════════════════════
  What would you like to do?

    [1] Patch a local boot.img file
    [2] Start the Telegram bot
    [0] Exit
```

---

### CLI flags

| Command | Description |
|---|---|
| `python3 main.py --list-versions` | Print all available Magisk versions and exit |
| `python3 main.py --patch boot.img` | Patch with interactive version picker |
| `python3 main.py --patch boot.img --version v30.7` | Fully non-interactive patch |
| `python3 main.py --patch boot.img --version v30.7 --output out.img` | Custom output path |
| `python3 main.py --bot` | Start Telegram bot directly |

#### Examples

```bash
# See what versions are available
python3 main.py --list-versions

# Patch interactively (prompts for version)
python3 main.py --patch /path/to/boot.img

# Fully automated — great for scripts
python3 main.py --patch boot.img --version v30.7 --output magisk-boot.img

# Start only the bot
python3 main.py --bot
```

#### Version key format

| Prefix | Channel | Example |
|---|---|---|
| `✅ v*` | Official (stable) | `v30.7` |
| `🧪 v*` | Delta (prerelease) | `v30.5` |
| `🐤 canary-*` | Alpha (canary) | `canary-29001` |

---

### Telegram Bot

Start the bot:

```bash
python3 main.py --bot
# or
python3 main.py   # then choose option [2]
```

**Bot commands:**

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Show help |
| `/root` | Reply to a `boot.img` attachment to start patching |

Or just **send a `boot.img` file directly** in private chat — the bot will show a version picker keyboard automatically.

Run in the background with `tmux`:

```bash
tmux new -s magisk
python3 main.py --bot
# Ctrl+B then D to detach
```

---

## Project Structure

```
MAGISK-FLASHER-V2/
├── main.py          # Everything: CLI, interactive menu, Telegram bot, patching core
├── config.py        # API credentials (edit this)
├── requirements.txt # Python dependencies
└── README.md
```

---

## How patching works

1. The selected Magisk APK is downloaded from GitHub Releases into a temp directory
2. The APK is unzipped to extract `magiskboot`, `boot_patch.sh`, and libraries
3. `boot_patch.sh boot.img` runs the standard Magisk patching process
4. The output `new-boot.img` is saved to your specified path (CLI) or sent back to the user (bot)
5. The temp directory is cleaned up automatically

---

## License

MIT
