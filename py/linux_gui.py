"""Small GTK app for the Linux extractor.

Shows the detected game process, runs the memory scan through pkexec
(graphical password prompt) and lets you save the result as data.json.

Usage:
    python3 linux_gui.py                     # start the app
    python3 linux_gui.py --install-launcher  # add it to your applications menu

Requires PyGObject (GTK 3) and msgpack, e.g. on Debian/Ubuntu/Mint:
    sudo apt install python3-gi gir1.2-gtk-3.0 python3-msgpack
"""
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linux_extract  # noqa: E402

APP_TITLE = "UmaExtractor"
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux_extract.py")
ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "umaguide_logo.ico")

HELPER_ERRORS = {
    2: "Game is not running.",
    3: "No veteran data found. Open the Veteran List page (Enhance → List) and wait for it to load.",
    4: "Permission denied while reading game memory.",
    126: "Authentication was cancelled.",
    127: "Not authorized to read game memory.",
}


def exe_basename(path):
    # argv[0] under Proton is usually a Windows path (Z:\...\Game.exe)
    return path.replace("\\", "/").rsplit("/", 1)[-1]


class ExtractorWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_TITLE)
        self.set_default_size(520, 360)
        self.set_border_width(12)
        if os.path.exists(ICON):
            try:
                self.set_icon_from_file(ICON)
            except GLib.Error:
                pass

        self.characters = None
        self.extracting = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(box)

        # Game process status
        frame = Gtk.Frame(label=" Game process ")
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_border_width(10)
        self.status_icon = Gtk.Image()
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_line_wrap(True)
        status_box.pack_start(self.status_icon, False, False, 0)
        status_box.pack_start(self.status_label, True, True, 0)
        frame.add(status_box)
        box.pack_start(frame, False, False, 0)

        hint = Gtk.Label(
            label="In-game, open Enhance → List (Veteran List) and wait for it to load, then click Extract.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        # Actions
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.extract_button = Gtk.Button(label="Extract")
        self.extract_button.get_style_context().add_class("suggested-action")
        self.extract_button.connect("clicked", self.on_extract)
        self.save_button = Gtk.Button(label="Save data.json…")
        self.save_button.set_sensitive(False)
        self.save_button.connect("clicked", self.on_save)
        self.spinner = Gtk.Spinner()
        buttons.pack_start(self.extract_button, False, False, 0)
        buttons.pack_start(self.save_button, False, False, 0)
        buttons.pack_start(self.spinner, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        self.result_label = Gtk.Label(xalign=0)
        self.result_label.set_line_wrap(True)
        self.result_label.set_selectable(True)
        box.pack_start(self.result_label, False, False, 0)

        # Log output
        expander = Gtk.Expander(label="Log")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(140)
        self.log_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scrolled.add(self.log_view)
        expander.add(scrolled)
        box.pack_start(expander, True, True, 0)

        self.game = None
        self.refresh_process()
        GLib.timeout_add_seconds(2, self.refresh_process)

    # -- process detection -------------------------------------------------

    def refresh_process(self):
        candidates = linux_extract.find_game_processes()
        self.game = candidates[0] if candidates else None

        if self.game:
            pid, path = self.game
            self.status_icon.set_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
            text = f"<b>{GLib.markup_escape_text(exe_basename(path))}</b>   PID {pid}"
            if len(candidates) > 1:
                text += f"\n<small>{len(candidates)} matching processes, using the first</small>"
            self.status_label.set_markup(text)
            self.status_label.set_tooltip_text(path)
        else:
            self.status_icon.set_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
            self.status_label.set_markup("Not running. Start Uma Musume Pretty Derby through Steam.")
            self.status_label.set_tooltip_text(None)

        self.extract_button.set_sensitive(self.game is not None and not self.extracting)
        return True

    # -- extraction --------------------------------------------------------

    def log(self, msg):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), msg.rstrip("\n") + "\n")
        self.log_view.scroll_to_mark(buf.get_insert(), 0, False, 0, 0)

    def on_extract(self, _button):
        self.extracting = True
        self.extract_button.set_sensitive(False)
        self.spinner.start()
        self.log_view.get_buffer().set_text("")
        self.result_label.set_text("Scanning game memory, this may take 30-60 seconds…")
        threading.Thread(target=self.run_helper, daemon=True).start()

    def run_helper(self):
        cmd = [sys.executable, "-I", HELPER, "--raw"]
        returncode, raw = self.run_command(cmd)

        # Wine usually allows same-user memory reads; ask for root only if needed
        if returncode == 4 and os.geteuid() != 0:
            GLib.idle_add(self.log, "Retrying with administrator rights (pkexec)…")
            try:
                returncode, raw = self.run_command(["pkexec"] + cmd)
            except FileNotFoundError:
                GLib.idle_add(self.finish, None, "pkexec not found. Install polkit or run this app as root.")
                return

        if returncode != 0:
            GLib.idle_add(self.finish, None, HELPER_ERRORS.get(returncode, f"Extraction failed (exit code {returncode})."))
            return

        try:
            characters = linux_extract.parse_characters(raw)
        except Exception as e:
            GLib.idle_add(self.finish, None, f"Could not parse data: {e}")
            return
        GLib.idle_add(self.finish, characters, None)

    def run_command(self, cmd):
        """Run the helper, streaming its stderr to the log. Returns (returncode, stdout)."""
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def pump_stderr():
            for line in iter(proc.stderr.readline, b""):
                GLib.idle_add(self.log, line.decode("utf-8", "replace"))

        log_thread = threading.Thread(target=pump_stderr, daemon=True)
        log_thread.start()
        raw = proc.stdout.read()
        proc.wait()
        log_thread.join()
        return proc.returncode, raw

    def finish(self, characters, error):
        self.extracting = False
        self.spinner.stop()
        self.refresh_process()

        if error:
            self.log(f"[X] {error}")
            self.result_label.set_markup(f"<span foreground='#c01c28'>{GLib.markup_escape_text(error)}</span>")
            return

        self.characters = characters
        self.save_button.set_sensitive(True)
        self.log(f"[OK] Parsed {len(characters)} characters (viewer IDs removed)")
        self.result_label.set_markup(f"<b>{len(characters)}</b> veteran umas extracted. Click Save to write data.json.")

    # -- saving ------------------------------------------------------------

    def on_save(self, _button):
        dialog = Gtk.FileChooserNative(
            title="Save data.json",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label="Save",
        )
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name("data.json")
        documents = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        dialog.set_current_folder(documents or os.path.expanduser("~"))

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            try:
                linux_extract.save_characters(self.characters, path)
            except OSError as e:
                self.result_label.set_markup(
                    f"<span foreground='#c01c28'>Could not save: {GLib.markup_escape_text(str(e))}</span>"
                )
            else:
                self.log(f"[OK] Saved to {path}")
                self.result_label.set_markup(
                    f"Saved {len(self.characters)} umas to <b>{GLib.markup_escape_text(path)}</b>"
                )
        dialog.destroy()


def install_launcher():
    apps_dir = os.path.join(GLib.get_user_data_dir(), "applications")
    os.makedirs(apps_dir, exist_ok=True)
    path = os.path.join(apps_dir, "uma-extractor.desktop")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_TITLE}\n"
            "Comment=Extract veteran Uma Musume data to data.json\n"
            f'Exec="{sys.executable}" "{os.path.abspath(__file__)}"\n'
            f"Icon={ICON}\n"
            "Terminal=false\n"
            "Categories=Utility;Game;\n"
        )
    print(f"Installed launcher: {path}")


def main():
    if "--install-launcher" in sys.argv[1:]:
        install_launcher()
        return

    app = Gtk.Application(application_id="io.github.wugerworks.UmaExtractor")
    app.connect("activate", lambda a: (a.get_active_window() or ExtractorWindow(a)).present())
    app.run(None)


if __name__ == "__main__":
    main()
