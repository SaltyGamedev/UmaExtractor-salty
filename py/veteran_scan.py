"""Platform-independent part of the veteran data extractor.

Finds the trained_chara_array msgpack blob in process memory regions and turns
it into JSON. The platform modules (linux_extract.py, windows_extract.py) only
list the memory regions of the game and read their bytes.

Only uses the standard library, except parse_characters() which needs msgpack.
"""
import json
import os
from datetime import datetime

# Pattern: "trained_chara_array" in msgpack format
# B3 = fixstr(19), followed by "trained_chara_array"
# The next byte is the array marker: fixarray (0x90-0x9F), array16 (0xDC), or array32 (0xDD)
PATTERN = b"\xb3trained_chara_array"

# Skip tiny (<16KB) and huge (>500MB) regions
MIN_REGION_SIZE = 16 * 1024
MAX_REGION_SIZE = 500 * 1024 * 1024

# Try different sizes (matching Frida script exactly)
PROBE_SIZES = [15 * 1024 * 1024, 20 * 1024 * 1024, 25 * 1024 * 1024]


class ExtractError(Exception):
    pass


def filter_regions(all_regions):
    """Keep regions of a useful size, largest first.

    Each region is a dict with "start", "end" and "size".
    Game data is likely in larger allocations.
    """
    regions = [r for r in all_regions if MIN_REGION_SIZE <= r["size"] <= MAX_REGION_SIZE]
    regions.sort(key=lambda r: r["size"], reverse=True)
    return regions


def find_in_region(data, region, log=print):
    """Look for a valid trained_chara_array in the bytes of one region.

    Returns the bytes starting at the array marker, or None.
    """
    # Search for pattern
    offset = data.find(PATTERN)
    if offset == -1:
        return None

    log(f"[OK] Found pattern at offset {hex(region['start'] + offset)}")

    # Array marker starts after: B3(1) + "trained_chara_array"(19) = 20 bytes
    array_start = offset + 20

    # Validate msgpack array header (matching Frida logic)
    if array_start >= len(data):
        return None
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
        return None

    log(f"  Array type byte: {hex(first_byte)}, declared length: {array_len}")

    for try_size in PROBE_SIZES:
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
            return bytes(potential_data)

    return None


def scan_regions(regions, read_region, log=print, progress=None):
    """Scan regions in order and return the first valid array, or None.

    read_region(region) returns the region's bytes, or None if it can't be
    read. Errors it raises (e.g. PermissionError) are passed on.
    progress(scanned, total), if given, is called after each region.
    """
    log("Searching for veteran character data...")
    log("This may take 30-60 seconds, please wait...")

    for scanned_count, region in enumerate(regions, 1):
        # Progress update every 10 ranges
        if scanned_count % 10 == 0:
            log(f"Progress: {scanned_count}/{len(regions)} regions scanned...")
        if progress:
            progress(scanned_count, len(regions))

        data = read_region(region)
        if data is None:
            continue

        found = find_in_region(data, region, log)
        if found is not None:
            return found

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


def save_export(character_array, export_dir):
    """Save to export_dir/data_<timestamp>.json and return the path."""
    path = os.path.join(export_dir, datetime.now().strftime("data_%Y-%m-%d_%H-%M-%S.json"))
    os.makedirs(export_dir, exist_ok=True)
    save_characters(character_array, path)
    return path
