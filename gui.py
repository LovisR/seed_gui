"""Unofficial XaeroSeed desktop GUI.

Build this application together with the upstream GPL-3.0 XaeroSeed project.
The Windows GitHub Actions workflow compiles the native engine and packages
this interface as a standalone executable with PyInstaller.
"""
from __future__ import annotations

import contextlib
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

APP_TITLE = "XaeroSeed — World Seed Finder"
DEFAULT_TOLERANCES = "16,24,32,48"


def bundled_file(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def worker_main(args: list[str]) -> int:
    # One executable supports both the GUI and the command-line worker.
    import xaeroseed
    xaeroseed.CRACKER = str(bundled_file("build", "seedcrack.exe"))
    if not Path(xaeroseed.CRACKER).exists():
        print(f"Missing compiled cracking engine: {xaeroseed.CRACKER}", flush=True)
        return 2
    sys.argv = ["xaeroseed"] + args
    return xaeroseed.main()


def locate_map_folder(root: Path) -> Path:
    if not root.is_dir():
        raise ValueError(f"Not a folder: {root}")
    # On maps created by Xaero, the desired directory has a dimension
    # subdirectory, usually `null` for the Overworld and `DIM-1` for Nether.
    def has_dimension(folder: Path) -> bool:
        try:
            return any(
                child.is_dir() and (child / "mw$default").is_dir()
                for child in folder.iterdir()
            )
        except OSError:
            return False
    if has_dimension(root):
        return root
    for folder, dirs, files in os.walk(root):
        depth = len(Path(folder).relative_to(root).parts)
        if depth > 4:
            dirs[:] = []
            continue
        if has_dimension(Path(folder)):
            return Path(folder)
    raise ValueError(
        "No Xaero World Map server folder found. Choose a Multiplayer_* "
        "folder, or the ZIP containing that folder."
    )


def safe_extract(archive: Path, dest: Path, log):
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        # Reject unsafe ZIP paths and symlinks.
        for info in members:
            name = info.filename.replace('\\', '/')
            parts = Path(name).parts
            if name.startswith('/') or '..' in parts or ':' in name:
                raise ValueError(f"Unsafe path in ZIP: {name}")
            mode = info.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise ValueError(f"Symbolic link not supported in ZIP: {name}")
            target = (dest / name).resolve()
            if not target.is_relative_to(base):
                raise ValueError(f"Unsafe ZIP file path: {name}")
        log(f"Extracting {len(members)} map files...")
        zf.extractall(dest)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("840x610")
        root.minsize(650, 460)
        self.map_path = tk.StringVar()
        self.threads = tk.StringVar(value=str(min(os.cpu_count() or 4, 8)))
        self.tolerances = tk.StringVar(value=DEFAULT_TOLERANCES)
        self.accept = tk.StringVar(value="0.85")
        self.status = tk.StringVar(value="Choose a Xaero World Map ZIP or server folder")
        self.event_queue: queue.Queue[tuple] = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.temp_dir: tempfile.TemporaryDirectory | None = None
        self.busy = False
        self.result_seed: str | None = None
        self._draw()
        self.root.after(80, self.poll)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _draw(self):
        root = self.root
        root.configure(bg="#101827")
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#101827")
        style.configure("TLabel", background="#101827", foreground="#d9e7fb", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 5))
        style.configure("TEntry", padding=4)
        style.configure("Header.TLabel", font=("Segoe UI", 20, "bold"), foreground="#76ddce")
        style.configure("Sub.TLabel", foreground="#a3b5ce")
        style.configure("Status.TLabel", foreground="#9cd8f5")
        content = ttk.Frame(root, padding=19)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="XaeroSeed", style="Header.TLabel").pack(anchor="w")
        ttk.Label(content, text="Find a Minecraft world seed from your explored Xaero World Map data", style="Sub.TLabel").pack(anchor="w", pady=(0, 15))
        ttk.Label(content, text="Xaero map ZIP or Multiplayer_* folder").pack(anchor="w")
        row = ttk.Frame(content)
        row.pack(fill="x", pady=(4, 12))
        ttk.Entry(row, textvariable=self.map_path).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text="Choose ZIP", command=self.choose_zip).pack(side="left", padx=(0, 5))
        ttk.Button(row, text="Choose folder", command=self.choose_folder).pack(side="left")
        opts = ttk.Frame(content)
        opts.pack(fill="x", pady=(0, 12))
        for i, (label, var, width) in enumerate([
            ("Threads", self.threads, 7),
            ("Origin tolerances", self.tolerances, 20),
            ("Min. match fraction", self.accept, 10),
        ]):
            group = ttk.Frame(opts)
            group.pack(side="left", padx=(0, 22))
            ttk.Label(group, text=label).pack(anchor="w")
            ttk.Entry(group, textvariable=var, width=width).pack(anchor="w", pady=4)
        bar = ttk.Frame(content)
        bar.pack(fill="x", pady=(0, 9))
        self.start_btn = ttk.Button(bar, text="Start seed search", command=self.start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Save log", command=self.save_log).pack(side="left", padx=(0, 8))
        self.copy_btn = ttk.Button(bar, text="Copy seed", command=self.copy_seed, state="disabled")
        self.copy_btn.pack(side="left")
        ttk.Label(content, textvariable=self.status, style="Status.TLabel").pack(anchor="w", pady=(0, 5))
        self.logbox = scrolledtext.ScrolledText(content, wrap="word", font=("Consolas", 10), bg="#0a1120", fg="#d5e7ed", insertbackground="white", bd=0, padx=12, pady=10)
        self.logbox.pack(fill="both", expand=True)
        self.log("Ready. Select your most recent Xaero world-map export.")
        self.log("Your data stays on this computer; the cracker does not upload your map.")

    def log(self, line: str):
        self.logbox.insert("end", str(line).rstrip() + "\n")
        self.logbox.see("end")

    def choose_zip(self):
        file = filedialog.askopenfilename(title="Select Xaero map ZIP", filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")])
        if file:
            self.map_path.set(file)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select Multiplayer_* Xaero map folder")
        if folder:
            self.map_path.set(folder)

    def start(self):
        if self.busy:
            return
        item = Path(self.map_path.get().strip('"'))
        if not item.exists():
            messagebox.showerror("Select a map", "Please select your Xaero map ZIP or server folder.")
            return
        try:
            n = int(self.threads.get())
            fraction = float(self.accept.get())
            tolerances = [int(x.strip()) for x in self.tolerances.get().split(',')]
            if not 1 <= n <= 256 or not 0 < fraction <= 1 or not tolerances or any(t <= 0 or t > 1000 for t in tolerances):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid options", "Threads: 1–256; match fraction: 0–1; tolerances: positive integers separated by commas.")
            return
        self.busy = True
        self.result_seed = None
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.copy_btn.configure(state="disabled")
        self.status.set("Preparing map...")
        self.log("\nStarting XaeroSeed search...")
        opts = ["--threads", str(n), "--accept", str(fraction), "--tolerances", ','.join(map(str, tolerances))]
        threading.Thread(target=self.run_job, args=(item, opts), daemon=True).start()

    def run_job(self, item: Path, opts: list[str]):
        try:
            if item.suffix.lower() == ".zip":
                self.temp_dir = tempfile.TemporaryDirectory(prefix="xaeroseed-map-")
                unpack = Path(self.temp_dir.name)
                safe_extract(item, unpack, lambda m: self.event_queue.put(("log", m)))
                server = locate_map_folder(unpack)
            else:
                server = locate_map_folder(item)
            self.event_queue.put(("log", f"Using map: {server.name}"))
            self.event_queue.put(("status", "Searching world seed..."))
            exe = sys.executable
            prefix = [exe, "--worker"] if getattr(sys, "frozen", False) else [exe, str(Path(__file__).resolve()), "--worker"]
            cmd = prefix + [str(server)] + opts
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1, **kwargs)
            assert self.process.stdout is not None
            for line in self.process.stdout:
                # Parse seed from the upstream 'seed <signed 64-bit number>' line.
                # Lines containing 'structure seed' must NOT be treated as results.
                match = re.match(r"^\s*seed\s+(-?\d+)\s*$", line)
                if match:
                    self.event_queue.put(("seed", match.group(1)))
                self.event_queue.put(("log", line.rstrip('\n\r')))
            status = self.process.wait()
            self.event_queue.put(("done", status))
        except Exception as exc:
            self.event_queue.put(("log", f"ERROR: {exc}"))
            self.event_queue.put(("done", 1))
        finally:
            self.process = None
            if self.temp_dir is not None:
                self.temp_dir.cleanup()
                self.temp_dir = None

    def poll(self):
        try:
            while True:
                kind, value = self.event_queue.get_nowait()
                if kind == "log":
                    self.log(value)
                elif kind == "seed":
                    self.result_seed = value
                    self.copy_btn.configure(state="normal")
                elif kind == "status":
                    self.status.set(value)
                elif kind == "done":
                    self.busy = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    if value == 0:
                        if self.result_seed:
                            self.status.set(f"Seed found: {self.result_seed}")
                        else:
                            self.status.set("No seed was printed — check engine output")
                            self.log("WARNING: Engine finished without a seed; not verified as successful.")
                    else:
                        self.status.set("No seed found / search failed — see log")
                    self.log(f"Search process finished (exit code {value}).")
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def stop(self):
        if not self.busy:
            return
        proc = self.process
        if proc and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.terminate()
        self.status.set("Stopping...")

    def copy_seed(self):
        if self.result_seed:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.result_seed)
            self.status.set("Seed copied to clipboard")

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text file", "*.txt")], initialfile="xaeroseed-search-log.txt")
        if path:
            Path(path).write_text(self.logbox.get("1.0", "end-1c"), encoding="utf-8")

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno("Stop seed search?", "A seed search is running. Stop it and exit?"):
                return
            self.stop()
        self.root.destroy()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        try:
            return worker_main(sys.argv[2:])
        except BaseException as exc:
            print(f"Worker error: {exc}", file=sys.stderr, flush=True)
            return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
