
import os
import sys
import time
import json
import shutil
import asyncio
import argparse
import tempfile
import subprocess
import urllib.request

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
cpath = str(os.getcwd())
GITHUB_API_URL = "https://api.github.com/repos/topjohnwu/Magisk/releases?per_page=50"

# Maps short version key -> APK download URL (populated by get_magisk_versions)
version_url_map = {}


# ─────────────────────────────────────────────
#  GitHub version fetcher
# ─────────────────────────────────────────────
def get_magisk_versions():
    """Fetch Magisk versions from GitHub Releases API.
    Categories:
      - Official : stable releases (prerelease=false, tag starts with 'v')
      - Delta    : prerelease builds (prerelease=true, tag starts with 'v')
      - Alpha    : canary builds (tag starts with 'canary')
    Returns up to 5 of each, newest first, as (display_label, version_key) tuples.
    Also populates the global version_url_map: version_key -> download URL."""
    global version_url_map
    version_url_map.clear()

    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "MagiskFlasherBot"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            releases = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[GitHub API] Failed to fetch releases: {e}")
        return []

    official = []
    delta    = []
    alpha    = []

    for release in releases:
        tag           = release.get("tag_name", "")
        is_prerelease = release.get("prerelease", False)
        assets        = release.get("assets", [])

        if tag.startswith("canary"):
            category = "alpha"
        elif is_prerelease:
            category = "delta"
        else:
            category = "official"

        apk_url = None
        for asset in assets:
            aname = asset.get("name", "")
            aurl  = asset.get("browser_download_url", "")
            if category in ("official", "delta") and aname.startswith("Magisk-") and aname.endswith(".apk"):
                apk_url = aurl
                break
            elif category == "alpha" and aname == "app-release.apk":
                apk_url = aurl
                break
        if category == "alpha" and not apk_url:
            for asset in assets:
                if asset.get("name") == "app-debug.apk":
                    apk_url = asset.get("browser_download_url")
                    break

        if not apk_url:
            continue

        key = tag
        version_url_map[key] = apk_url

        if category == "official" and len(official) < 5:
            official.append((f"✅ {key}", key))
        elif category == "delta" and len(delta) < 5:
            delta.append((f"🧪 {key}", key))
        elif category == "alpha" and len(alpha) < 5:
            alpha.append((f"🐤 {key}", key))

        if len(official) >= 5 and len(delta) >= 5 and len(alpha) >= 5:
            break

    return official + delta + alpha


# ─────────────────────────────────────────────
#  Core patching logic (shared by CLI + bot)
# ─────────────────────────────────────────────
def download_apk(version_key: str, dest_path: str) -> bool:
    """Download the APK for a given version key. Returns True on success."""
    url = version_url_map.get(version_key)
    if not url:
        print(f"  [!] No URL found for version '{version_key}'. Refreshing list...")
        get_magisk_versions()
        url = version_url_map.get(version_key)
    if not url:
        print(f"  [!] Version '{version_key}' not found in release list.")
        return False
    print(f"  → Downloading {version_key} from GitHub...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"  [!] Download failed: {e}")
        return False


def patch_boot_img(boot_img_path: str, version_key: str, work_dir: str, output_path: str = None) -> str | None:
    """
    Patch a boot.img with the given Magisk version.
    work_dir  : temp directory where APK is extracted and patching happens
    output_path: where to copy the finished new-boot.img (None = stay in work_dir)
    Returns the final path of the patched image, or None on failure.
    """
    boot_img_path = os.path.abspath(boot_img_path)
    if not os.path.exists(boot_img_path):
        print(f"  [!] boot.img not found: {boot_img_path}")
        return None

    apk_path = os.path.join(work_dir, f"{version_key}.apk")

    # Download if not cached
    if not os.path.exists(apk_path):
        if not download_apk(version_key, apk_path):
            return None

    print(f"  → Unzipping {version_key}.apk ...")
    subprocess.run(["unzip", "-o", apk_path, "-d", work_dir],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Copy boot.img into work dir
    shutil.copy2(boot_img_path, os.path.join(work_dir, "boot.img"))

    commands = [
        "mv assets/boot_patch.sh boot_patch.sh",
        "mv assets/util_functions.sh util_functions.sh",
        "mv assets/stub.apk stub.apk",
        "mv lib/x86_64/libmagiskboot.so magiskboot",
        "mv lib/armeabi-v7a/libmagisk32.so magisk32",
        "mv lib/arm64-v8a/libmagisk64.so magisk64",
        "mv lib/arm64-v8a/libmagiskinit.so magiskinit",
        "rm -rf assets lib META-INF res",
        "sed -i 's/function ui_print() {/ui_print() { echo \"$1\"/' util_functions.sh",
        "sed -i 's/getprop/adb shell getprop/g' util_functions.sh",
        "sh boot_patch.sh boot.img",
    ]

    print("  → Running Magisk boot patcher...")
    for cmd in commands:
        subprocess.run(["sh", "-c", cmd], cwd=work_dir)

    patched    = os.path.join(work_dir, "new-boot.img")
    named      = os.path.join(work_dir, f"boot_{version_key}.img")

    if not os.path.exists(patched):
        print("  [!] Patching failed — new-boot.img was not produced.")
        return None

    # Rename to boot_{version}.img
    os.rename(patched, named)

    if output_path:
        shutil.copy2(named, output_path)
        print(f"  ✅ Patched image saved to: {output_path}")
        return output_path
    else:
        print(f"  ✅ Patched image: {named}")
        return named


# ─────────────────────────────────────────────
#  Interactive CLI mode
# ─────────────────────────────────────────────
def _pick_version_interactively() -> str | None:
    """Show a numbered menu of Magisk versions and return the chosen key."""
    print("\n  Fetching Magisk versions from GitHub...")
    versions = get_magisk_versions()
    if not versions:
        print("  [!] Could not fetch versions. Check your internet connection.")
        return None

    print("\n  Available versions:\n")
    for i, (label, key) in enumerate(versions, 1):
        print(f"    [{i:2}] {label}  ({key})")

    print()
    while True:
        try:
            choice = input("  Select a version (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(versions):
                return versions[idx][1]
            print(f"  [!] Enter a number between 1 and {len(versions)}.")
        except (ValueError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return None


def cli_local_mode():
    """Interactive: patch a local boot.img file."""
    print("\n" + "═" * 52)
    print("  MAGISK FLASHER — Local Patch Mode")
    print("═" * 52)

    while True:
        boot_img = input("\n  Path to boot.img (or drag & drop here): ").strip().strip("'\"")
        if os.path.exists(boot_img):
            break
        print(f"  [!] File not found: {boot_img}")

    version_key = _pick_version_interactively()
    if not version_key:
        return

    default_out = os.path.join(os.path.dirname(os.path.abspath(boot_img)), f"boot_{version_key}.img")
    out_prompt  = input(f"\n  Output path [{default_out}]: ").strip().strip("'\"")
    output_path = out_prompt if out_prompt else default_out

    work_dir = tempfile.mkdtemp(prefix="magisk_flash_")
    try:
        result = patch_boot_img(boot_img, version_key, work_dir, output_path)
        if not result:
            print("\n  ❌ Patching failed.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_interactive_menu():
    """Top-level menu when main.py is run with no arguments."""
    print("\n" + "═" * 52)
    print("  MAGISK FLASHER v2")
    print("═" * 52)
    print("\n  What would you like to do?\n")
    print("    [1] Patch a local boot.img file")
    print("    [2] Start the Telegram bot")
    print("    [0] Exit\n")

    choice = input("  Choice: ").strip()

    if choice == "1":
        cli_local_mode()
    elif choice == "2":
        run_bot()
    elif choice == "0":
        sys.exit(0)
    else:
        print("  [!] Invalid choice.")


# ─────────────────────────────────────────────
#  Telegram bot
# ─────────────────────────────────────────────
def run_bot():
    """Import telethon and start the Telegram bot."""
    try:
        from telethon.sync import TelegramClient, events
        from telethon import Button
        from FastTelethonhelper import fast_download
    except ImportError as e:
        print(f"  [!] Missing dependency for bot mode: {e}")
        print("      Run: pip install telethon FastTelethonhelper")
        sys.exit(1)

    from config import API_ID, API_HASH, BOT_TOKEN

    client = TelegramClient(None, API_ID, API_HASH).start(bot_token=BOT_TOKEN)
    group_user_ids = {}
    user_download_directories = {}
    bot_start_time = time.time()

    print("\n  Starting Telegram bot...\n")

    # ── /start ──────────────────────────────────
    @client.on(events.NewMessage(pattern='/start'))
    async def start(event):
        await event.reply(
            "Welcome to the Magisk Boot Patcher Bot!\n\n"
            "This bot can help you patch and flash Magisk to your boot.img file.\n\n"
            "Supported Commands:\n"
            "/help - Show this help message.\n"
            "Send me stock-boot.img file or reply /root to your stock-boot.img to initiate the patching process.\n\n"
            "For any assistance or issues, you can contact our support:\n"
            "Telegram Support group: @nub_coder_s\n"
        )
        user_id   = str(event.sender_id)
        user_path = os.path.join(cpath, user_id)
        try:
            shutil.rmtree(user_path)
        except Exception:
            pass

    # ── Auto cleanup task ────────────────────────
    async def cleanup_old_directories():
        while True:
            await asyncio.sleep(600)  # check every 10 minutes
            now = time.time()
            for item in os.listdir(cpath):
                if item.isdigit():  # User directories are just sender_ids (numbers)
                    dir_path = os.path.join(cpath, item)
                    if os.path.isdir(dir_path):
                        mtime = os.path.getmtime(dir_path)
                        if now - mtime > 3600:  # older than 1 hour
                            try:
                                shutil.rmtree(dir_path)
                                print(f"  [Cleanup] Removed old directory: {dir_path}")
                            except Exception as e:
                                print(f"  [Cleanup] Error removing {dir_path}: {e}")

    # ── /ping ────────────────────────────────────
    @client.on(events.NewMessage(pattern='/ping'))
    async def ping(event):
        t0  = time.time()
        msg = await event.respond("Pong!")
        ms  = round((time.time() - t0) * 1000)

        elapsed = int(time.time() - bot_start_time)
        days,  rem  = divmod(elapsed, 86400)
        hours, rem  = divmod(rem, 3600)
        mins,  secs = divmod(rem, 60)
        
        uptime = f"{mins}m {secs}s"
        if hours:
            uptime = f"{hours}h {uptime}"
        if days:
            uptime = f"{days}d {uptime}"

        await msg.edit(f"🏓 Pong! `{ms} ms`\n⏱️ Uptime: `{uptime}`")

    # ── /help ────────────────────────────────────
    @client.on(events.NewMessage(pattern='/help'))
    async def help_command(event):
        await event.respond(
            "Welcome to the Magisk Flasher Bot!\n\n"
            "This bot can help you patch and flash Magisk to your boot.img file.\n\n"
            "Supported Commands:\n"
            "/start - Start the bot and upload your boot.img file.\n"
            "/help  - Show this help message.\n"
            "/ping  - Check bot latency and uptime.\n"
            "/root  - Reply to a file with this command to initiate the patching process.\n\n"
            "For any assistance or issues, you can contact our support:\n"
            "Telegram Support Username: @nub_coder_s\n"
        )

    # ── Build version keyboard (shared helper) ───
    async def _build_keyboard():
        versions = await asyncio.to_thread(get_magisk_versions)
        if not versions:
            return None, None
        keyboard = []
        for i in range(0, len(versions), 2):
            row = []
            label1, key1 = versions[i]
            row.append(Button.inline(label1, f"dl:{key1}".encode()))
            if i + 1 < len(versions):
                label2, key2 = versions[i + 1]
                row.append(Button.inline(label2, f"dl:{key2}".encode()))
            keyboard.append(row)
        keyboard.append([Button.inline("Cancel", b"cancel")])
        return keyboard, versions

    # ── File upload handler ──────────────────────
    @client.on(events.NewMessage(func=lambda e: e.document and e.is_private))
    async def download_and_rename_file(event):
        nonlocal group_user_ids
        user = await event.get_sender()
        user_id = user.id
        group = await client.get_entity("@nub_coder_s")

        async for member in client.iter_participants(group):
            group_user_ids[member.id] = True

        if user_id not in group_user_ids:
            btn = Button.url("Join", "https://t.me/nub_coder_s")
            await event.respond(
                "You need to join @nub_coder_s in order to use this bot.\n\nClick below to Join!",
                buttons=btn
            )
            return
        group_user_ids.clear()

        if event.file.size >= 200_000_000:
            await event.reply('please send a file less than 200MB')
            return

        user_id       = event.sender_id
        user_directory = os.path.join(cpath, str(user_id))
        try:
            shutil.rmtree(user_directory)
        except Exception:
            pass
        os.makedirs(user_directory, exist_ok=True)

        gg = await event.reply("Downloading file, please wait for some time")
        await client.download_media(event.document, f"{user_directory}/boot.img")

        keyboard, _ = await _build_keyboard()
        if not keyboard:
            await gg.delete()
            await event.respond("⚠️ Could not fetch Magisk versions from GitHub. Please try again later.")
            return

        user_download_directories[user_id] = user_directory
        await gg.delete()
        await event.respond("Please select a Magisk version:\nLatest version recommended", buttons=keyboard)

    # ── /root handler ────────────────────────────
    @client.on(events.NewMessage(pattern='/root'))
    async def handle_root(event):
        if not (event.is_reply and event.message.reply_to_msg_id):
            await event.respond('Please reply to a file with the /root command.')
            return

        replied_message = await event.get_reply_message()
        if not replied_message.document:
            await event.respond('The replied message does not contain a document.')
            return

        document = replied_message.document
        if document.size >= 200_000_000:
            await event.reply('Please send a file less than 200MB.')
            return

        user_id        = event.sender_id
        user_directory = os.path.join(cpath, str(user_id))
        try:
            shutil.rmtree(user_directory)
        except Exception:
            pass
        os.makedirs(user_directory, exist_ok=True)

        gg = await event.respond("Downloading file, please wait for some time")
        await client.download_media(document, f"{user_directory}/boot.img")

        keyboard, _ = await _build_keyboard()
        if not keyboard:
            await gg.delete()
            await event.respond("⚠️ Could not fetch Magisk versions from GitHub. Please try again later.")
            return

        user_download_directories[user_id] = user_directory
        await gg.delete()
        await event.reply("Please select a Magisk version:", buttons=keyboard)

    # ── Callback: version selected ───────────────
    @client.on(events.CallbackQuery())
    async def handle_magisk_version(event):
        user_id        = event.sender_id
        user_directory = os.path.join(cpath, str(user_id))
        raw_data       = event.data.decode("utf-8")

        if raw_data == "cancel":
            return

        if raw_data.startswith("dl:"):
            version_key  = raw_data[3:]
            version_text = version_key
        else:
            version_key  = raw_data
            version_text = raw_data

        await event.edit(f"You selected: {version_text}. Downloading & patching boot.img…")

        boot_img_path = os.path.join(user_directory, "boot.img")
        
        def do_patch():
            return patch_boot_img(boot_img_path, version_key, user_directory, None)
            
        patched_path = await asyncio.to_thread(do_patch)

        if patched_path and os.path.exists(patched_path):
            await event.edit("Repack boot.img successfully\nNow uploading, please wait…")
            await event.respond(
                file=patched_path,
                message=f"✅ Boot.img patched with Magisk {version_text}"
            )
        else:
            await event.edit(
                "❌ No patched image was generated.\n\n"
                "This may not be a valid boot.img — please try again with the original stock image."
            )

        # Cleanup immediately to save space, fallback to 1-hour auto-cleanup if this fails
        try:
            shutil.rmtree(user_directory, ignore_errors=True)
        except Exception:
            pass

    # ── Cancel callback ──────────────────────────
    @client.on(events.CallbackQuery(data=b"cancel"))
    async def handle_cancel(event):
        user_id        = event.sender_id
        user_directory = user_download_directories.get(user_id)
        if user_directory:
            try:
                shutil.rmtree(user_directory)
            except Exception as e:
                print(f"An error occurred while deleting user directory: {e}")
            await event.delete()
        else:
            await event.answer("This message is not for you.")

    client.loop.create_task(cleanup_old_directories())
    client.run_until_disconnected()


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="magisk-flasher",
        description="Magisk Boot Image Patcher — CLI, interactive, or Telegram bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # interactive menu
  python main.py --bot                    # start Telegram bot directly
  python main.py --patch boot.img         # patch with interactive version picker
  python main.py --patch boot.img --version v30.7
  python main.py --patch boot.img --version v30.7 --output patched.img
  python main.py --list-versions          # show all available Magisk versions
        """
    )

    parser.add_argument(
        "--patch", metavar="BOOT_IMG",
        help="Path to the stock boot.img to patch"
    )
    parser.add_argument(
        "--version", metavar="VERSION_KEY",
        help="Magisk version key to use (e.g. v30.7, canary-29001). "
             "Run --list-versions to see all options."
    )
    parser.add_argument(
        "--output", metavar="OUT_IMG", default=None,
        help="Output path for the patched image (default: boot_{version}.img next to input)"
    )
    parser.add_argument(
        "--bot", action="store_true",
        help="Start the Telegram bot"
    )
    parser.add_argument(
        "--list-versions", action="store_true",
        help="List all available Magisk versions and exit"
    )

    args = parser.parse_args()

    # ── --list-versions ──────────────────────────
    if args.list_versions:
        print("\n  Fetching Magisk versions from GitHub...\n")
        versions = get_magisk_versions()
        if not versions:
            print("  [!] Could not fetch versions.")
            sys.exit(1)
        for label, key in versions:
            print(f"  {label}  →  {key}")
        print()
        sys.exit(0)

    # ── --bot ────────────────────────────────────
    if args.bot:
        run_bot()
        return

    # ── --patch ──────────────────────────────────
    if args.patch:
        boot_img = args.patch

        # Resolve version
        if args.version:
            version_key = args.version
            # Make sure version_url_map is populated
            get_magisk_versions()
            if version_key not in version_url_map:
                print(f"\n  [!] Version '{version_key}' not found. Run --list-versions to see valid keys.")
                sys.exit(1)
        else:
            version_key = _pick_version_interactively()
            if not version_key:
                sys.exit(1)

        # Resolve output path
        if args.output:
            output_path = args.output
        else:
            output_path = os.path.join(
                os.path.dirname(os.path.abspath(boot_img)), "new-boot.img"
            )

        work_dir = tempfile.mkdtemp(prefix="magisk_flash_")
        try:
            result = patch_boot_img(boot_img, version_key, work_dir, output_path)
            sys.exit(0 if result else 1)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ── No args → interactive menu ───────────────
    run_interactive_menu()


if __name__ == "__main__":
    main()
