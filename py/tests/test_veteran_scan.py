"""Tests for the shared scanner and the Linux memory reader.

Run from the project root:
    python3 -m unittest discover -s py/tests
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import veteran_scan  # noqa: E402

try:
    import msgpack
except ImportError:
    msgpack = None

MARKER = b"\xa7card_id"


def blob(array_header, body=b""):
    return veteran_scan.PATTERN + array_header + body


def region_for(data, start=0x10000):
    return {"start": start, "end": start + len(data), "size": len(data)}


def quiet(_msg):
    pass


class FindInRegionTest(unittest.TestCase):
    def check(self, data):
        return veteran_scan.find_in_region(data, region_for(data), quiet)

    def test_fixarray_with_card_id(self):
        data = b"\x00" * 100 + blob(b"\x92", MARKER + b"\x01" * 2000)
        found = self.check(data)
        self.assertIsNotNone(found)
        self.assertEqual(found[:1], b"\x92")
        self.assertEqual(found, data[100 + len(veteran_scan.PATTERN):])

    def test_array16_and_array32(self):
        for header in (b"\xdc\x01\x00", b"\xdd\x00\x00\x01\x00"):
            data = blob(header, MARKER + b"\x00" * 2000)
            self.assertEqual(self.check(data)[:1], header[:1])

    def test_empty_array_accepted_without_card_id(self):
        data = blob(b"\x90", b"\x00" * 2000)
        self.assertIsNotNone(self.check(data))

    def test_rejects_missing_card_id(self):
        self.assertIsNone(self.check(blob(b"\x92", b"\x00" * 2000)))

    def test_rejects_unknown_marker(self):
        self.assertIsNone(self.check(blob(b"\xc0", MARKER + b"\x00" * 2000)))

    def test_rejects_too_little_data_after_pattern(self):
        self.assertIsNone(self.check(blob(b"\x92", MARKER)))

    def test_no_pattern(self):
        self.assertIsNone(self.check(b"\x00" * 4096))


class ScanRegionsTest(unittest.TestCase):
    def test_skips_unreadable_and_reports_progress(self):
        good = blob(b"\x91", MARKER + b"\x00" * 2000)
        regions = [region_for(b"\x00" * 10), region_for(good, 0x20000)]
        contents = {0x10000: None, 0x20000: good}
        seen = []
        found = veteran_scan.scan_regions(
            regions, lambda r: contents[r["start"]], quiet, lambda s, t: seen.append((s, t))
        )
        self.assertIsNotNone(found)
        self.assertEqual(seen, [(1, 2), (2, 2)])

    def test_passes_on_permission_error(self):
        def read(_region):
            raise PermissionError

        with self.assertRaises(PermissionError):
            veteran_scan.scan_regions([region_for(b"x")], read, quiet)

    def test_filter_regions(self):
        sizes = [1024, 32 * 1024, 600 * 1024 * 1024, 1024 * 1024]
        regions = veteran_scan.filter_regions([{"start": 0, "end": s, "size": s} for s in sizes])
        self.assertEqual([r["size"] for r in regions], [1024 * 1024, 32 * 1024])


@unittest.skipIf(msgpack is None, "msgpack not installed")
class ParseAndSaveTest(unittest.TestCase):
    def test_parse_scrubs_viewer_ids(self):
        packed = msgpack.packb([{"card_id": 1, "viewer_id": 5, "owner_viewer_id": 6, "speed": 900}])
        self.assertEqual(veteran_scan.parse_characters(packed + b"\x00" * 100), [{"card_id": 1, "speed": 900}])

    def test_parse_rejects_non_array(self):
        with self.assertRaises(veteran_scan.ExtractError):
            veteran_scan.parse_characters(msgpack.packb({"card_id": 1}))

    def test_save_export_timestamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "exports")
            path = veteran_scan.save_export([{"card_id": 1}], export_dir)
            self.assertEqual(os.path.dirname(path), export_dir)
            self.assertRegex(os.path.basename(path), r"^data_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.json$")


# Child process that keeps a fake veteran roster in memory until stdin closes
FAKE_GAME = r"""
import sys, msgpack
roster = msgpack.packb([{"card_id": 100101, "viewer_id": 42, "speed": 1200}, {"card_id": 100201, "speed": 900}])
data = bytearray(1024 * 1024)
payload = b"\xb3trained_chara_array" + roster
data[4096:4096 + len(payload)] = payload
print("ready", flush=True)
sys.stdin.read()
"""


@unittest.skipUnless(sys.platform.startswith("linux") and msgpack, "Linux with msgpack only")
class LinuxEndToEndTest(unittest.TestCase):
    def test_finds_roster_in_fake_game_process(self):
        import linux_extract

        argv0 = "Z:\\Games\\UmamusumePrettyDerby.exe"
        # exec -a sets argv[0], which is what find_game_processes matches on
        proc = subprocess.Popen(
            ["bash", "-c", f'exec -a "{argv0}" "{sys.executable}" -c "$0"', FAKE_GAME],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), b"ready")
            pids = [pid for pid, _ in linux_extract.find_game_processes()]
            self.assertIn(proc.pid, pids)

            try:
                raw = linux_extract.scan_for_veteran_data(proc.pid, quiet)
            except PermissionError:
                self.skipTest("ptrace restrictions block reading child memory")
            self.assertIsNotNone(raw)
            characters = veteran_scan.parse_characters(raw)
            self.assertEqual(characters, [{"card_id": 100101, "speed": 1200}, {"card_id": 100201, "speed": 900}])
        finally:
            proc.stdin.close()
            proc.wait(timeout=10)
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
