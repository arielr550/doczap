"""DocZap's desktop window: choose Word documents, choose where the PDFs go, convert."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Iterable
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from doczap import system
from doczap.batch import Job, Result, format_summary, plan_jobs, plural, run_jobs
from doczap.converters.libreoffice import find_soffice
from doczap.utils.file_ops import SUPPORTED_INPUTS

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
LIBREOFFICE_DOWNLOAD_URL = "https://www.libreoffice.org/download/download-libreoffice/"
WORD_FILE_TYPES = [("Word documents", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_INPUTS)))]
EMPTY_HINT = "Add the Word documents you want to turn into PDFs."
BESIDE, FOLDER = "beside", "folder"


def display_folder(folder: Path) -> str:
    """Show a folder the way people read it, with ~ for the home folder on macOS and Linux."""
    if sys.platform != "win32":
        try:
            return str(Path("~") / folder.relative_to(Path.home()))
        except ValueError:
            pass
    return str(folder)


class App:
    def __init__(self, root: tk.Tk, files: Iterable[str] = ()) -> None:
        self.root = root
        self.sources: list[Path] = []
        self.output_dir: Path | None = None
        self.destination = tk.StringVar(value=BESIDE)
        self.folder_label = tk.StringVar(value="No folder chosen")
        self.status = tk.StringVar(value=EMPTY_HINT)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.busy = False
        self.started = 0
        self.last_output: Path | None = None

        self.build()
        self.add_files(files)

    # Layout

    def build(self) -> None:
        root = self.root
        root.title("DocZap")
        root.minsize(560, 480)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        base = font.nametofont("TkDefaultFont").actual()
        title_font = font.Font(root, family=base["family"], size=abs(base["size"]) + 9, weight="bold")
        heading_font = font.Font(root, family=base["family"], size=abs(base["size"]), weight="bold")

        page = ttk.Frame(root, padding=20)
        page.grid(sticky="nsew")
        page.columnconfigure(0, weight=1)

        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="w", pady=(0, 16))
        self.logo = tk.PhotoImage(file=str(LOGO_PATH))
        ttk.Label(header, image=self.logo).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ttk.Label(header, text="DocZap", font=title_font).grid(row=0, column=1, sticky="sw")
        ttk.Label(
            header, text="Word to PDF with the layout intact. Your documents never leave this computer."
        ).grid(row=1, column=1, sticky="nw")
        if sys.platform != "darwin":
            # macOS takes the Dock icon from the app bundle; elsewhere Tk shows its own.
            root.iconphoto(True, self.logo)

        row = 1
        if find_soffice() is None:
            notice = ttk.Frame(page)
            notice.grid(row=row, column=0, sticky="ew", pady=(0, 16))
            notice.columnconfigure(0, weight=1)
            ttk.Label(
                notice,
                text="LibreOffice is not installed. DocZap uses it to lay out your documents.",
                wraplength=380,
            ).grid(row=0, column=0, sticky="w")
            ttk.Button(
                notice,
                text="Download LibreOffice",
                command=lambda: webbrowser.open(LIBREOFFICE_DOWNLOAD_URL),
            ).grid(row=0, column=1, padx=(12, 0))
            row += 1

        ttk.Label(page, text="Documents", font=heading_font).grid(row=row, column=0, sticky="w")
        list_frame = ttk.Frame(page)
        list_frame.grid(row=row + 1, column=0, sticky="nsew", pady=(6, 8))
        page.rowconfigure(row + 1, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_frame, columns=("name", "folder"), show="headings", height=6, selectmode="extended"
        )
        self.tree.heading("name", text="Name", anchor="w")
        self.tree.heading("folder", text="Folder", anchor="w")
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("folder", width=280, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.update_controls())
        self.tree.bind("<Delete>", lambda event: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda event: self.remove_selected())

        list_buttons = ttk.Frame(page)
        list_buttons.grid(row=row + 2, column=0, sticky="w", pady=(0, 16))
        self.add_button = ttk.Button(list_buttons, text="Add Documents…", command=self.choose_files)
        self.add_button.grid(row=0, column=0)
        self.remove_button = ttk.Button(list_buttons, text="Remove", command=self.remove_selected)
        self.remove_button.grid(row=0, column=1, padx=(8, 0))

        ttk.Label(page, text="Save PDFs", font=heading_font).grid(row=row + 3, column=0, sticky="w")
        self.beside_option = ttk.Radiobutton(
            page,
            text="Next to each document",
            variable=self.destination,
            value=BESIDE,
            command=self.update_controls,
        )
        self.beside_option.grid(row=row + 4, column=0, sticky="w", pady=(6, 2))
        folder_row = ttk.Frame(page)
        folder_row.grid(row=row + 5, column=0, sticky="ew")
        folder_row.columnconfigure(1, weight=1)
        self.folder_option = ttk.Radiobutton(
            folder_row,
            text="In this folder:",
            variable=self.destination,
            value=FOLDER,
            command=self.folder_option_selected,
        )
        self.folder_option.grid(row=0, column=0, sticky="w")
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_label, state="readonly")
        self.folder_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.choose_folder_button = ttk.Button(folder_row, text="Choose…", command=self.choose_folder)
        self.choose_folder_button.grid(row=0, column=2)

        ttk.Separator(page).grid(row=row + 6, column=0, sticky="ew", pady=16)
        footer = ttk.Frame(page)
        footer.grid(row=row + 7, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.progress.grid_remove()
        ttk.Label(footer, textvariable=self.status, wraplength=300).grid(row=1, column=0, sticky="w")
        self.reveal_button = ttk.Button(
            footer, text=f"Show in {system.file_manager_name()}", command=self.reveal
        )
        self.reveal_button.grid(row=1, column=1, padx=(8, 0))
        self.reveal_button.grid_remove()
        self.convert_button = ttk.Button(
            footer, text="Convert to PDF", command=self.convert, default="active"
        )
        self.convert_button.grid(row=1, column=2, padx=(8, 0))

        modifier = "Command" if sys.platform == "darwin" else "Control"
        root.bind(f"<{modifier}-o>", lambda event: self.choose_files())
        root.bind("<Return>", lambda event: self.convert())
        if sys.platform == "darwin":
            # Documents dropped on the Dock icon or opened with "Open With".
            root.createcommand("::tk::mac::OpenDocument", lambda *paths: self.add_files(paths))

        self.refresh_list()

    # Documents

    def choose_files(self) -> None:
        if self.busy:
            return
        initial = self.sources[-1].parent if self.sources else Path.home()
        files = filedialog.askopenfilenames(
            parent=self.root,
            title="Add Word documents",
            initialdir=initial,
            filetypes=WORD_FILE_TYPES,
        )
        self.add_files(files)

    def add_files(self, files: Iterable[str]) -> None:
        if self.busy:
            return
        added = ignored = 0
        for name in files:
            path = Path(name).expanduser().resolve()
            if path.suffix.lower() not in SUPPORTED_INPUTS or not path.is_file():
                ignored += 1
            elif path not in self.sources:
                self.sources.append(path)
                added += 1
        self.refresh_list()
        if ignored:
            kind = "is not a Word document" if ignored == 1 else "are not Word documents"
            self.status.set(f"Ignored {plural(ignored, 'file')} that {kind}.")
        elif added:
            self.status.set("")

    def remove_selected(self) -> None:
        if self.busy:
            return
        selected = {Path(item) for item in self.tree.selection()}
        self.sources = [path for path in self.sources if path not in selected]
        self.refresh_list()
        if not self.sources:
            self.status.set(EMPTY_HINT)

    def refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for path in self.sources:
            self.tree.insert("", "end", iid=str(path), values=(path.name, display_folder(path.parent)))
        self.update_controls()

    # Destination

    def folder_option_selected(self) -> None:
        if self.output_dir is None:
            self.choose_folder()
        self.update_controls()

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self.root,
            title="Save PDFs in",
            initialdir=self.output_dir or Path.home(),
            mustexist=True,
        )
        if folder:
            self.output_dir = Path(folder).resolve()
            self.folder_label.set(display_folder(self.output_dir))
            self.destination.set(FOLDER)
        elif self.output_dir is None:
            self.destination.set(BESIDE)
        self.update_controls()

    def chosen_output_dir(self) -> Path | None:
        return self.output_dir if self.destination.get() == FOLDER else None

    # Conversion

    def convert(self) -> None:
        if self.busy or not self.sources:
            return
        output_dir = self.chosen_output_dir()
        if output_dir is not None and not output_dir.is_dir():
            messagebox.showerror(
                "Folder not found",
                f"{output_dir} no longer exists. Choose another folder.",
                parent=self.root,
            )
            return

        jobs = plan_jobs(self.sources, output_dir)
        existing = [job for job in jobs if job.output.exists()]
        skipped = 0
        if existing:
            replace = self.ask_replace(existing)
            if replace is None:
                return
            for job in existing:
                job.replace = replace
            if not replace:
                jobs = [job for job in jobs if job not in existing]
                skipped = len(existing)
        if not jobs:
            self.status.set(format_summary(Result(), skipped))
            return

        self.set_busy(True)
        self.started = 0
        self.progress.configure(maximum=len(jobs), value=0)
        threading.Thread(target=self.work, args=(jobs, skipped), daemon=True).start()
        self.root.after(100, self.poll)

    def ask_replace(self, existing: list[Job]) -> bool | None:
        """Ask once for all existing PDFs. None means the user cancelled."""
        if len(existing) == 1:
            job = existing[0]
            message = f"{job.output.name} already exists."
            detail = f"It is in {display_folder(job.output.parent)}. Replace it?"
        else:
            names = "\n".join(job.output.name for job in existing[:8])
            more = f"\n…and {len(existing) - 8} more" if len(existing) > 8 else ""
            message = f"{len(existing)} PDFs already exist."
            detail = f"{names}{more}\n\nReplace them? Choose No to skip these documents."
        return messagebox.askyesnocancel(
            "Replace existing PDFs?",
            message,
            detail=detail,
            icon=messagebox.WARNING,
            default=messagebox.NO,
            parent=self.root,
        )

    def work(self, jobs: list[Job], skipped: int) -> None:
        # Runs on a background thread, so it only talks to the window through the queue.
        result = run_jobs(jobs, on_start=lambda job: self.events.put(("start", job)))
        self.events.put(("done", result, skipped))

    def poll(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "start":
                self.progress.configure(value=self.started)
                self.started += 1
                total = int(self.progress["maximum"])
                self.status.set(f"Converting {event[1].source.name} ({self.started} of {total})…")
            else:
                self.finish(event[1], event[2])
                return
        self.root.after(100, self.poll)

    def finish(self, result: Result, skipped: int) -> None:
        self.set_busy(False)
        # Converted documents leave the list; failed and skipped ones stay to try again.
        done = {job.source for job in result.converted}
        self.sources = [path for path in self.sources if path not in done]
        self.refresh_list()
        self.status.set(format_summary(result, skipped))
        if result.converted:
            self.last_output = result.converted[-1].output
            self.reveal_button.grid()
        if result.errors:
            messagebox.showerror(
                "Some documents were not converted",
                "\n\n".join(result.errors),
                parent=self.root,
            )

    def reveal(self) -> None:
        if self.last_output is not None:
            system.reveal(self.last_output)

    # State

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.progress.grid()
            self.reveal_button.grid_remove()
            self.root.configure(cursor="watch")
        else:
            self.progress.grid_remove()
            self.root.configure(cursor="")
        self.update_controls()

    def update_controls(self) -> None:
        def enable(widget: ttk.Widget, enabled: bool) -> None:
            widget.state(["!disabled"] if enabled else ["disabled"])

        idle = not self.busy
        has_selection = bool(self.tree.selection())
        enable(self.add_button, idle)
        enable(self.remove_button, idle and has_selection)
        enable(self.beside_option, idle)
        enable(self.folder_option, idle)
        enable(self.choose_folder_button, idle)
        can_convert = idle and bool(self.sources)
        enable(self.convert_button, can_convert)
        # On macOS a default button stays blue even when disabled.
        self.convert_button.configure(default="active" if can_convert else "normal")

    def quit(self) -> None:
        if self.busy and not messagebox.askokcancel(
            "Quit DocZap?",
            "A conversion is still running. Quit anyway?",
            icon=messagebox.WARNING,
            parent=self.root,
        ):
            return
        self.root.destroy()


def main() -> int:
    # macOS passes a -psn_ process serial number when an app is opened from Finder.
    files = [arg for arg in sys.argv[1:] if not arg.startswith("-psn_")]
    system.enable_high_dpi()
    root = tk.Tk()
    App(root, files)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
