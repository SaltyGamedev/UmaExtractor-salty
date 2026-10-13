# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "msgpack",
# ]
# ///
"""Uma Musume veteran data extractor for Linux (Steam/Proton).

Usage:
    sudo python3 linux_extract.py          # scan and write data.json
    sudo python3 linux_extract.py --raw    # helper mode: raw msgpack bytes to stdout

The --raw mode only uses the standard library and writes all log output to
stderr. It is used by linux_gui.py, which runs it through pkexec.
"""
import json
import os
import sys

TARGET_PROCESS = "umamusumeprettyderby.exe"

# Pattern: "trained_chara_array" in msgpack format
# B3 = fixstr(19), followed by "trained_chara_array"
# The next byte is the array marker: fixarray (0x90-0x9F), array16 (0xDC), or array32 (0xDD)
PATTERN = b"\xb3trained_chara_array"


class ExtractError(Exception):
    pass


def find_game_processes():
    """Return a list of (pid, argv0) for running game processes.

    Matches on argv[0] to avoid Proton wrappers. Does not require root.
    """
    candidates = []
    for pid_dir in os.listdir("/proc"):
        if not pid_dir.isdigit():
            continue

        try:
            with open(f"/proc/{pid_dir}/cmdline", "rb") as f:
                cmdline_bytes = f.read()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue

        if not cmdline_bytes:
            continue

        argv0 = cmdline_bytes.split(b"\x00", 1)[0].decode("utf-8", "replace")
        if argv0.lower().endswith(TARGET_PROCESS):
            candidates.append((int(pid_dir), argv0))

    candidates.sort()
    return candidates


def read_memory_regions(pid):
    """Return read-write memory regions of the process, largest first."""
    all_regions = []
    with open(f"/proc/{pid}/maps", "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue

            # Parse address range
            addr_range = parts[0]
            perms = parts[1]

            # We want read-write regions (rw)
            if "rw" not in perms:
                continue

            # Parse start and end addresses
            start, end = addr_range.split("-")
            start_addr = int(start, 16)
            end_addr = int(end, 16)
            size = end_addr - start_addr

            all_regions.append({"start": start_addr, "end": end_addr, "size": size})

    # Filter and sort ranges: skip tiny (<16KB) and huge (>500MB) ranges
    # Sort by size descending - game data is likely in larger allocations
    memory_regions = [
        r for r in all_regions if r["size"] >= 16 * 1024 and r["size"] <= 500 * 1024 * 1024
    ]
    memory_regions.sort(key=lambda r: r["size"], reverse=True)
    return memory_regions, len(all_regions)


def scan_for_veteran_data(pid, log=print):
    """Scan process memory for the trained_chara_array msgpack blob.

    Returns the raw bytes starting at the array marker, or None if not found.
    Raises PermissionError if process memory can't be read.
    """
    log("Reading process memory maps...")
    memory_regions, total = read_memory_regions(pid)
    log(f"Scanning {len(memory_regions)} memory regions (filtered from {total})...")
    log("Searching for veteran character data...")
    log("This may take 30-60 seconds, please wait...")

    with open(f"/proc/{pid}/mem", "rb") as mem:
        for scanned_count, region in enumerate(memory_regions, 1):
            # Progress update every 10 ranges
            if scanned_count % 10 == 0:
                log(f"Progress: {scanned_count}/{len(memory_regions)} regions scanned...")

            try:
                # Seek to region start and read the entire region
                mem.seek(region["start"])
                data = mem.read(region["size"])
            except (OSError, IOError):
                # Some regions may not be readable, skip them
                continue

            # Search for pattern
            offset = data.find(PATTERN)
            if offset == -1:
                continue

            log(f"[OK] Found pattern at offset {hex(region['start'] + offset)}")

            # Array marker starts after: B3(1) + "trained_chara_array"(19) = 20 bytes
            array_start = offset + 20

            # Validate msgpack array header (matching Frida logic)
            if array_start >= len(data):
                continue
            first_byte = data[array_start]
            array_len = -1
            if 0x90 <= first_byte <= 0x9F:
                array_len = first_byte - 0x90  # fixarray (0-15 items)
            elif first_byte == 0xDC and array_start + 2 < len(data):
                array_len = (data[array_start + 1] << 8) | data[array_start + 2]  # array16
            elif first_byte == 0xDD and array_start + 4 < len(data):
                array_len = (
                    (data[array_start + 1] << 24)
                    + (data[array_start + 2] << 16)
                    + (data[array_start + 3] << 8)
                    + data[array_start + 4]
                )  # array32
            else:
                log(f"  Unknown array marker byte: {hex(first_byte)}, skipping")
                continue

            log(f"  Array type byte: {hex(first_byte)}, declared length: {array_len}")

            # Try different sizes (matching Frida script exactly)
            sizes = [15 * 1024 * 1024, 20 * 1024 * 1024, 25 * 1024 * 1024]

            for try_size in sizes:
                # Calculate max size we can read from this region
                max_read_size = min(try_size, region["size"] - array_start)

                if max_read_size < 1024:
                    continue

                # Extract the potential array data (include the array marker)
                potential_data = data[array_start : array_start + max_read_size]

                # Quick validation: count occurrences of "card_id"
                # Check only first 3MB for performance (matching Frida)
                # Look for: A7 63 61 72 64 5f 69 64 (fixstr(7) + "card_id")
                card_id_pattern = b"\xa7card_id"
                check_data = potential_data[: 3 * 1024 * 1024]
                card_count = check_data.count(card_id_pattern)

                log(f"  Size {try_size // (1024 * 1024)}MB: Found {card_count} card_id entries")

                # Accept empty arrays or any array with at least 1 card_id
                # (matching Frida validation logic)
                if array_len == 0 or card_count >= 1:
                    log(f"[OK] Found valid array (len={array_len}) with {card_count} card_id matches!")
                    return potential_data

    return None


def parse_characters(raw):
    """Decode the msgpack array and scrub personal information."""
    import msgpack

    unpacker = msgpack.Unpacker(raw=False)
    unpacker.feed(raw)
    character_array = unpacker.unpack()

    if not isinstance(character_array, list):
        raise ExtractError(f"Expected array but got {type(character_array)}")

    # Remove personal information
    for char in character_array:
        char.pop("viewer_id", None)
        char.pop("owner_viewer_id", None)
    return character_array


def save_characters(character_array, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(character_array, f, indent=2, ensure_ascii=False)


def run_raw_helper():
    """Helper mode for the GUI: raw bytes to stdout, logs to stderr.

    Exit codes: 0 found, 2 game not running, 3 data not found, 4 permission denied.
    """
    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    candidates = find_game_processes()
    if not candidates:
        log("[X] Could not find game process")
        sys.exit(2)

    pid, name = candidates[0]
    log(f"[OK] Found game process: {name} (PID: {pid})")

    try:
        raw = scan_for_veteran_data(pid, log)
    except PermissionError:
        log("[X] Permission denied when reading process memory")
        sys.exit(4)

    if raw is None:
        log("[X] No veteran data found")
        sys.exit(3)

    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main():
    print("=== Uma Musume Veteran Data Extractor (Linux Edition) ===\n")

    # Find the game process
    print("Searching for game process...")
    try:
        candidates = find_game_processes()
    except Exception as e:
        print(f"[X] Error searching for process: {e}")
        sys.exit(1)

    if not candidates:
        print("[X] Error: Could not find game process")
        print("  Make sure Uma Musume Pretty Derby is running")
        print("  Looking for: UmamusumePrettyDerby.exe")
        sys.exit(1)

    game_pid, game_name = candidates[0]
    if len(candidates) > 1:
        print(f"[!] Multiple game processes found, using PID {game_pid}:")
        for pid, name in candidates:
            print(f"    PID {pid}: {name}")
    print(f"[OK] Found game process: {game_name} (PID: {game_pid})\n")

    try:
        found_data = scan_for_veteran_data(game_pid)
    except PermissionError:
        print("\n[X] Permission denied when reading process memory")
        print("  You need to run this script as root:")
        print(f"  sudo python3 {sys.argv[0]}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] Error reading memory: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    if found_data is None:
        print("\n[X] No veteran data found")
        print("\nTroubleshooting:")
        print("  1. Make sure you're on the Veteran List page (Enhance -> Veteran Umamusume -> List)")
        print("  2. Wait for the page to fully load")
        print(f"  3. Try running this script as root: sudo python3 {sys.argv[0]}")
        sys.exit(1)

    # Parse the msgpack data
    print("\nProcessing data...")
    try:
        character_array = parse_characters(found_data)
        print(f"[OK] Successfully parsed {len(character_array)} characters")
        print("[OK] Removed viewer_id and owner_viewer_id fields")

        # Save to JSON - try current directory first, then fallback to home directory
        output_file = "data.json"
        try:
            save_characters(character_array, output_file)
            output_file = os.path.abspath(output_file)
            print(f"[OK] Saved to {output_file}\n")
        except PermissionError:
            output_file = os.path.join(os.path.expanduser("~"), "data.json")
            try:
                save_characters(character_array, output_file)
                print(f"[OK] Saved to {output_file}\n")
                print("    (Saved to home directory due to permission issue in current directory)")
            except PermissionError:
                print("[X] Error: Permission denied when saving file.")
                print("    Please make sure data.json is not open in another program,")
                print("    or try running this program from a different folder.")
                raise ExtractError("Could not save data.json - permission denied")

        # Show summary
        if len(character_array) > 0:
            first_char = character_array[0]
            print("Sample character data:")
            print(f"  - card_id: {first_char.get('card_id', 'N/A')}")
            print(f"  - speed: {first_char.get('speed', 'N/A')}")
            print(f"  - stamina: {first_char.get('stamina', 'N/A')}")
            print(f"  - power: {first_char.get('power', 'N/A')}")
            print(f"  - guts: {first_char.get('guts', 'N/A')}")
            print(f"  - wisdom: {first_char.get('wiz', 'N/A')}")

            if "factor_id_array" in first_char:
                print(f"  - factors: {first_char['factor_id_array']}")

        print(f"\n[SUCCESS] Extracted {len(character_array)} veteran umas to {output_file}")

    except Exception as e:
        print(f"[X] Error processing data: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if "--raw" in sys.argv[1:]:
        run_raw_helper()
    else:
        main()
