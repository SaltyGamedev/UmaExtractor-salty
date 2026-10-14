# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "msgpack",
# ]
# ///
"""Uma Musume veteran data extractor for Windows.

Shows the detected game process, scans its memory in the background and saves
the result to exports/data_<timestamp>.json.

Usage:
    python extract_umas.py         # start the app
    python extract_umas.py --cli   # scan and write data.json to the current folder
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import veteran_scan
import windows_extract

APP_TITLE = "UmaExtractor"


def resource_path(*parts):
    if hasattr(sys, "_MEIPASS"):
        base_dir = getattr(sys, "_MEIPASS")
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_dir, *parts)


def default_export_dir():
    """exports/ next to the .exe, or in the project folder when run from source."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_dir, "exports")


FALLBACK_EXPORT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "UmaExtractor", "exports")

ERROR_MESSAGES = {
    "not_running": "Game is not running.",
    "no_data": "No veteran data found. Open the Veteran List page (Enhance → List) and wait for it to load.",
    "permission": "Access denied while reading game memory.",
}


def extract(log, progress=None):
    """Find the game, scan it and parse the data.

    Returns (characters, error_key). error_key is one of ERROR_MESSAGES, or
    None on success. Other errors are raised.
    """
    candidates = windows_extract.find_game_processes()
    if not candidates:
        log("[X] Could not find game process")
        return None, "not_running"

    pid, name = candidates[0]
    if len(candidates) > 1:
        log(f"[!] Multiple game processes found, using PID {pid}")
    log(f"[OK] Found game process: {name} (PID: {pid})")

    try:
        raw = windows_extract.scan_for_veteran_data(pid, log, progress)
    except PermissionError:
        log("[X] Permission denied when reading process memory")
        return None, "permission"

    if raw is None:
        log("[X] No veteran data found")
        return None, "no_data"

    log("Processing data...")
    characters = veteran_scan.parse_characters(raw)
    log(f"[OK] Parsed {len(characters)} characters (viewer IDs removed)")
    return characters, None


class UmaExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self._set_window_icon()
        self.root.geometry("620x480")
        self.root.minsize(480, 360)

        self.message_queue = queue.Queue()
        self.extracting = False
        self.game = None
        self.export_dir = default_export_dir()

        self._build_ui()
        self.refresh_process()
        self.root.after(100, self._drain_queue)

    def _set_window_icon(self):
        icon_path = resource_path("assets", "umaguide_logo.ico")
        if not os.path.exists(icon_path):
            return
        try:
            self.root.iconbitmap(icon_path)
        except Exception:
            # Keep running even if icon loading fails on a specific platform/environment.
            pass

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        # Game process status
        frame = ttk.LabelFrame(container, text=" Game process ", padding=10)
        frame.pack(fill=tk.X)
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold"))
        self.status_label.pack(anchor="w")
        self.status_detail_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.status_detail_var).pack(anchor="w")

        hint = ttk.Label(
            container,
            text="In-game, open Enhance → List (Veteran List) and wait for it to load, then click Extract.",
            foreground="gray40",
            wraplength=560,
            justify=tk.LEFT,
        )
        hint.pack(anchor="w", pady=(10, 10))

        # Actions
        btn_row = ttk.Frame(container)
        btn_row.pack(fill=tk.X)
        self.extract_btn = ttk.Button(btn_row, text="Extract", command=self.on_extract)
        self.extract_btn.pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Open exports folder", command=self.on_open_folder).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Copy log", command=self.on_copy_log).pack(side=tk.RIGHT, padx=(0, 8))

        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(container, mode="determinate", maximum=100, variable=self.progress_var).pack(
            fill=tk.X, pady=(10, 6)
        )

        self.result_var = tk.StringVar()
        self.result_label = ttk.Label(container, textvariable=self.result_var, wraplength=560, justify=tk.LEFT)
        self.result_label.pack(anchor="w", pady=(0, 6))

        # Log output
        self.log_box = scrolledtext.ScrolledText(container, wrap=tk.WORD, height=12, font=("Consolas", 9))
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.configure(state=tk.DISABLED)

    # -- process detection -------------------------------------------------

    def refresh_process(self):
        try:
            candidates = windows_extract.find_game_processes()
        except OSError as e:
            candidates = []
            self.status_detail_var.set(f"Could not list processes: {e}")
        self.game = candidates[0] if candidates else None

        if self.game:
            pid, name = self.game
            self.status_var.set(f"✔  {name}   PID {pid}")
            self.status_label.configure(foreground="#26a269")
            self.status_detail_var.set(
                f"{len(candidates)} matching processes, using the first" if len(candidates) > 1 else ""
            )
        else:
            self.status_var.set("⚠  Not running")
            self.status_label.configure(foreground="#c64600")
            self.status_detail_var.set("Start Uma Musume Pretty Derby through Steam.")

        self.extract_btn.configure(state=tk.NORMAL if self.game and not self.extracting else tk.DISABLED)
        self.root.after(2000, self.refresh_process)

    # -- extraction --------------------------------------------------------

    def log(self, message):
        ts = time.strftime("%H:%M:%S")
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, f"[{ts}] {message.rstrip()}\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def on_extract(self):
        if self.extracting:
            return
        self.extracting = True
        self.extract_btn.configure(state=tk.DISABLED)
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state=tk.DISABLED)
        self.progress_var.set(0.0)
        self.result_label.configure(foreground="")
        self.result_var.set("Scanning game memory, this may take 30-60 seconds…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        def log(msg):
            self.message_queue.put(("log", msg))

        def progress(scanned, total):
            self.message_queue.put(("progress", scanned * 100.0 / total))

        try:
            characters, error_key = extract(log, progress)
        except Exception as e:
            self.message_queue.put(("done", (None, None, f"Extraction failed: {type(e).__name__}: {e}")))
            return
        self.message_queue.put(("done", (characters, error_key, None)))

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "progress":
                    self.progress_var.set(payload)
                elif kind == "done":
                    self.finish(*payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def show_error(self, error):
        self.log(f"[X] {error}")
        self.progress_var.set(0.0)
        self.result_label.configure(foreground="#c01c28")
        self.result_var.set(error)

    def finish(self, characters, error_key, error):
        self.extracting = False
        self.extract_btn.configure(state=tk.NORMAL if self.game else tk.DISABLED)

        if error_key == "permission" and not windows_extract.is_admin():
            self.show_error(ERROR_MESSAGES[error_key])
            if messagebox.askyesno(
                APP_TITLE,
                "Windows denied access to the game's memory.\n\n"
                "This usually means the game runs as administrator. "
                "Restart UmaExtractor as administrator?",
            ):
                if windows_extract.relaunch_as_admin():
                    self.root.destroy()
            return
        if error_key or error:
            self.show_error(ERROR_MESSAGES.get(error_key, error))
            return

        try:
            path = self.save(characters)
        except OSError as e:
            self.show_error(f"Could not save: {e}")
            return

        self.log(f"[OK] Saved to {path}")
        self.progress_var.set(100.0)
        self.result_label.configure(foreground="")
        self.result_var.set(f"Saved {len(characters)} veteran umas to {path}")

    def save(self, characters):
        try:
            return veteran_scan.save_export(characters, self.export_dir)
        except PermissionError:
            # e.g. the .exe sits in a folder the user can't write to
            self.log(f"[!] Can't write to {self.export_dir}, using {FALLBACK_EXPORT_DIR}")
            self.export_dir = FALLBACK_EXPORT_DIR
            return veteran_scan.save_export(characters, self.export_dir)

    def on_open_folder(self):
        try:
            os.makedirs(self.export_dir, exist_ok=True)
        except PermissionError:
            self.export_dir = FALLBACK_EXPORT_DIR
            os.makedirs(self.export_dir, exist_ok=True)
        os.startfile(self.export_dir)

    def on_copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_box.get("1.0", tk.END))
        self.result_label.configure(foreground="")
        self.result_var.set("Log copied to clipboard.")


def safe_pause(prompt="\nPress Enter to exit..."):
    try:
        input(prompt)
    except EOFError:
        pass


def save_output(character_array):
    """Save data.json to the current folder, or to Documents if that isn't writable."""
    output_file = os.path.abspath("data.json")
    try:
        veteran_scan.save_characters(character_array, output_file)
    except PermissionError:
        output_file = os.path.join(os.path.expanduser("~"), "Documents", "data.json")
        veteran_scan.save_characters(character_array, output_file)
        print("    (Saved to Documents folder due to permission issue in current directory)")
    return output_file


def run_cli():
    print("=== Uma Musume Veteran Data Extractor ===\n")
    try:
        characters, error_key = extract(print)
        if error_key:
            print(f"\n[X] {ERROR_MESSAGES[error_key]}")
            if error_key == "permission":
                print("    Run this program as administrator.")
            return 1
        output_file = save_output(characters)
    except Exception as e:
        print(f"[X] Error: {type(e).__name__}: {e}")
        return 1

    print(f"[OK] Saved to {output_file}")
    print(f"\n[SUCCESS] Extracted {len(characters)} veteran umas to {output_file}")
    return 0


def run_gui():
    root = tk.Tk()
    UmaExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        code = run_cli()
        safe_pause()
        sys.exit(code)
    run_gui()
