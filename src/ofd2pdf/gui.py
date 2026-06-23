from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .converter import convert_file
from .exceptions import OfdConversionError


@dataclass(frozen=True)
class QueueEvent:
    kind: str
    payload: object = None


class Ofd2PdfApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OFD to PDF")
        self.minsize(860, 560)

        self.files: list[Path] = []
        self.status_by_file: dict[Path, str] = {}
        self.events: queue.Queue[QueueEvent] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.output_dir = tk.StringVar(value=str(Path.cwd() / "output" / "pdf"))
        self.overwrite = tk.BooleanVar(value=True)
        self.recursive = tk.BooleanVar(value=True)

        self._build_ui()
        self.after(100, self._process_events)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill=tk.X)

        self.add_files_button = ttk.Button(toolbar, text="Add OFD Files", command=self.add_files)
        self.add_files_button.pack(side=tk.LEFT)
        self.add_folder_button = ttk.Button(toolbar, text="Add Folder", command=self.add_folder)
        self.add_folder_button.pack(side=tk.LEFT, padx=(8, 0))
        self.remove_button = ttk.Button(toolbar, text="Remove Selected", command=self.remove_selected)
        self.remove_button.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_button = ttk.Button(toolbar, text="Clear", command=self.clear_files)
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        options = ttk.Frame(root)
        options.pack(fill=tk.X, pady=(12, 8))

        ttk.Label(options, text="Output folder").grid(row=0, column=0, sticky=tk.W)
        output_entry = ttk.Entry(options, textvariable=self.output_dir)
        output_entry.grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))
        ttk.Button(options, text="Browse", command=self.choose_output_dir).grid(row=0, column=2)
        options.columnconfigure(1, weight=1)

        ttk.Checkbutton(options, text="Overwrite existing PDFs", variable=self.overwrite).grid(
            row=1, column=1, sticky=tk.W, pady=(8, 0)
        )
        ttk.Checkbutton(options, text="Recursive folder import", variable=self.recursive).grid(
            row=1, column=2, sticky=tk.W, pady=(8, 0)
        )

        table_frame = ttk.Frame(root)
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        self.table = ttk.Treeview(table_frame, columns=("path", "status"), show="headings", selectmode="extended")
        self.table.heading("path", text="OFD file")
        self.table.heading("status", text="Status")
        self.table.column("path", width=640, anchor=tk.W)
        self.table.column("status", width=140, anchor=tk.W)

        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=yscroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X)

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.start_button = ttk.Button(bottom, text="Convert", command=self.start_conversion)
        self.start_button.pack(side=tk.LEFT, padx=(8, 0))
        self.open_output_button = ttk.Button(bottom, text="Open Output Folder", command=self.open_output_folder)
        self.open_output_button.pack(side=tk.LEFT, padx=(8, 0))

        self.log = tk.Text(root, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, pady=(10, 0))

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select OFD files",
            filetypes=[("OFD files", "*.ofd"), ("All files", "*.*")],
        )
        self._add_paths(Path(path) for path in paths)

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder containing OFD files")
        if not folder:
            return
        root = Path(folder)
        pattern = "**/*.ofd" if self.recursive.get() else "*.ofd"
        found = sorted(path for path in root.glob(pattern) if path.is_file())
        self._add_paths(found)
        self._write_log(f"Added {len(found)} OFD file(s) from {root}")

    def _add_paths(self, paths) -> None:
        existing = set(self.files)
        added = 0
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved.suffix.lower() != ".ofd" or not resolved.is_file() or resolved in existing:
                continue
            self.files.append(resolved)
            existing.add(resolved)
            self.status_by_file[resolved] = "Pending"
            self.table.insert("", tk.END, iid=str(resolved), values=(str(resolved), "Pending"))
            added += 1
        if added:
            self._write_log(f"Added {added} OFD file(s).")

    def remove_selected(self) -> None:
        for item in self.table.selection():
            path = Path(item)
            if path in self.files:
                self.files.remove(path)
            self.status_by_file.pop(path, None)
            self.table.delete(item)

    def clear_files(self) -> None:
        self.files.clear()
        self.status_by_file.clear()
        for item in self.table.get_children():
            self.table.delete(item)
        self.progress["value"] = 0

    def choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    def start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("OFD to PDF", "Please add at least one OFD file.")
            return

        out_dir_text = self.output_dir.get().strip()
        out_dir = Path(out_dir_text).expanduser().resolve() if out_dir_text else None
        self.progress["maximum"] = len(self.files)
        self.progress["value"] = 0
        self._set_controls_enabled(False)
        self._write_log("Starting conversion...")

        self.worker = threading.Thread(
            target=self._convert_worker,
            args=(list(self.files), out_dir, self.overwrite.get()),
            daemon=True,
        )
        self.worker.start()

    def _convert_worker(self, files: list[Path], out_dir: Path | None, overwrite: bool) -> None:
        completed = 0
        failures = 0
        for source in files:
            self.events.put(QueueEvent("status", (source, "Converting")))
            try:
                target = (out_dir / f"{source.stem}.pdf") if out_dir else source.with_suffix(".pdf")
                convert_file(source, target, overwrite=overwrite)
            except Exception as exc:
                failures += 1
                message = str(exc) or exc.__class__.__name__
                self.events.put(QueueEvent("status", (source, "Failed")))
                self.events.put(QueueEvent("log", f"Failed: {source}\n  {message}"))
            else:
                completed += 1
                self.events.put(QueueEvent("status", (source, "Done")))
                self.events.put(QueueEvent("log", f"Done: {source}"))
            finally:
                self.events.put(QueueEvent("progress", completed + failures))
        self.events.put(QueueEvent("finished", (completed, failures)))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event.kind == "status":
                    source, status = event.payload
                    self._set_status(source, status)
                elif event.kind == "progress":
                    self.progress["value"] = int(event.payload)
                elif event.kind == "log":
                    self._write_log(str(event.payload))
                elif event.kind == "finished":
                    completed, failures = event.payload
                    self._set_controls_enabled(True)
                    self._write_log(f"Finished. Converted: {completed}. Failed: {failures}.")
                    if failures:
                        messagebox.showwarning("OFD to PDF", f"Finished with {failures} failure(s).")
                    else:
                        messagebox.showinfo("OFD to PDF", f"Converted {completed} file(s).")
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _set_status(self, source: Path, status: str) -> None:
        self.status_by_file[source] = status
        item = str(source)
        if self.table.exists(item):
            self.table.set(item, "status", status)

    def _write_log(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.start_button,
        ):
            widget.configure(state=state)

    def open_output_folder(self) -> None:
        out_dir_text = self.output_dir.get().strip()
        path = Path(out_dir_text).expanduser().resolve() if out_dir_text else Path.cwd()
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("OFD to PDF", f"Could not open folder:\n{exc}")


def main() -> int:
    try:
        app = Ofd2PdfApp()
        app.mainloop()
    except OfdConversionError as exc:
        messagebox.showerror("OFD to PDF", str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
