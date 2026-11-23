"""DocZap's desktop window: convert Word documents to PDF, or merge PDFs into one."""

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
from doczap.merge import merge_pdfs
from doczap.utils.file_ops import SUPPORTED_INPUTS, FileIdentity, file_identity

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
LIBREOFFICE_DOWNLOAD_URL = "https://www.libreoffice.org/download/download-libreoffice/"
WORD_FILE_TYPES = [("Word documents", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_INPUTS)))]
PDF_FILE_TYPES = [("PDF documents", "*.pdf")]
EMPTY_HINT = "Add the Word documents you want to turn into PDFs."
MERGE_HINT = "Add the PDFs to merge. Their pages follow the list order, top to bottom."
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
        self.pdfs: list[Path] = []
        self.merge_status = tk.StringVar(value=MERGE_HINT)
        self.merged_output: Path | None = None
        self.events: queue.Queue[tuple] = queue.Queue()
        self.busy = False
        self.closing = False
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.started = 0
        self.last_output: Path | None = None

        self.build()
        self.open_files(files)

    # Layout

    def build(self) -> None:
        root = self.root
        root.title("DocZap")
        root.minsize(560, 520)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        base = font.nametofont("TkDefaultFont").actual()
        title_font = font.Font(root, family=base["family"], size=abs(base["size"]) + 9, weight="bold")
        self.heading_font = font.Font(root, family=base["family"], size=abs(base["size"]), weight="bold")

        window = ttk.Frame(root, padding=20)
        window.grid(sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        header = ttk.Frame(window)
        header.grid(row=0, column=0, sticky="w", pady=(0, 16))
        self.logo = tk.PhotoImage(file=str(LOGO_PATH))
        ttk.Label(header, image=self.logo).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ttk.Label(header, text="DocZap", font=title_font).grid(row=0, column=1, sticky="sw")
        ttk.Label(
            header, text="Word to PDF with the layout intact. Your files never leave this computer."
        ).grid(row=1, column=1, sticky="nw")
        if sys.platform != "darwin":
            # macOS takes the Dock icon from the app bundle; elsewhere Tk shows its own.
            root.iconphoto(True, self.logo)

        self.notebook = ttk.Notebook(window)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        convert_page = ttk.Frame(self.notebook, padding=16)
        merge_page = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(convert_page, text="Convert to PDF")
        self.notebook.add(merge_page, text="Merge PDFs")
        self.build_convert(convert_page)
        self.build_merge(merge_page)

        modifier = "Command" if sys.platform == "darwin" else "Control"
        root.bind(f"<{modifier}-o>", lambda event: self.add_on_current_tab())
        root.bind("<Return>", lambda event: self.run_current_tab())
        if sys.platform == "darwin":
            # Documents dropped on the Dock icon or opened with "Open With".
            root.createcommand("::tk::mac::OpenDocument", lambda *paths: self.open_files(paths))
            root.createcommand("::tk::mac::Quit", self.quit)

        self.refresh_list()
        self.refresh_merge_list()

    def merge_tab_selected(self) -> bool:
        return self.notebook.index("current") == 1

    def add_on_current_tab(self) -> None:
        if self.merge_tab_selected():
            self.choose_pdfs()
        else:
            self.choose_files()

    def run_current_tab(self) -> None:
        if self.merge_tab_selected():
            self.merge()
        else:
            self.convert()

    def open_files(self, files: Iterable[str]) -> None:
        """Files from the command line or the Dock: PDFs go to the merge tab."""
        files = list(files)
        pdfs = [name for name in files if Path(name).suffix.lower() == ".pdf"]
        documents = [name for name in files if name not in pdfs]
        self.add_files(documents)
        if pdfs:
            self.add_pdfs(pdfs)
            if not documents:
                self.notebook.select(1)

    def build_convert(self, page: ttk.Frame) -> None:
        heading_font = self.heading_font
        page.columnconfigure(0, weight=1)
        row = 0
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

    def build_merge(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(page, text="PDFs, in order", font=self.heading_font).grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(page)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.merge_tree = ttk.Treeview(
            list_frame, columns=("name", "folder"), show="headings", height=6, selectmode="extended"
        )
        self.merge_tree.heading("name", text="Name", anchor="w")
        self.merge_tree.heading("folder", text="Folder", anchor="w")
        self.merge_tree.column("name", width=200, anchor="w")
        self.merge_tree.column("folder", width=280, anchor="w")
        self.merge_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.merge_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.merge_tree.configure(yscrollcommand=scrollbar.set)
        self.merge_tree.bind("<<TreeviewSelect>>", lambda event: self.update_controls())
        self.merge_tree.bind("<Delete>", lambda event: self.remove_selected_pdfs())
        self.merge_tree.bind("<BackSpace>", lambda event: self.remove_selected_pdfs())

        buttons = ttk.Frame(page)
        buttons.grid(row=2, column=0, sticky="w")
        self.add_pdfs_button = ttk.Button(buttons, text="Add PDFs…", command=self.choose_pdfs)
        self.add_pdfs_button.grid(row=0, column=0)
        self.remove_pdfs_button = ttk.Button(buttons, text="Remove", command=self.remove_selected_pdfs)
        self.remove_pdfs_button.grid(row=0, column=1, padx=(8, 0))
        self.move_up_button = ttk.Button(buttons, text="Move Up", command=lambda: self.move_selected_pdfs(-1))
        self.move_up_button.grid(row=0, column=2, padx=(8, 0))
        self.move_down_button = ttk.Button(
            buttons, text="Move Down", command=lambda: self.move_selected_pdfs(1)
        )
        self.move_down_button.grid(row=0, column=3, padx=(8, 0))

        ttk.Separator(page).grid(row=3, column=0, sticky="ew", pady=16)
        footer = ttk.Frame(page)
        footer.grid(row=4, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.merge_status, wraplength=300).grid(row=0, column=0, sticky="w")
        self.merge_reveal_button = ttk.Button(
            footer, text=f"Show in {system.file_manager_name()}", command=self.reveal_merged
        )
        self.merge_reveal_button.grid(row=0, column=1, padx=(8, 0))
        self.merge_reveal_button.grid_remove()
        self.merge_button = ttk.Button(footer, text="Merge PDFs", command=self.merge)
        self.merge_button.grid(row=0, column=2, padx=(8, 0))

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
        try:
            for job in jobs:
                job.replace_only = file_identity(job.output)
        except OSError as exc:
            messagebox.showerror("Could not check output files", str(exc), parent=self.root)
            return
        existing = [job for job in jobs if job.replace_only is not None]
        skipped = 0
        if existing:
            replace = self.ask_replace(existing)
            if replace is None:
                return
            if not replace:
                jobs = [job for job in jobs if job.replace_only is None]
                skipped = len(existing)
        if not jobs:
            self.status.set(format_summary(Result(), skipped))
            return

        self.set_busy(True)
        self.progress.grid()
        self.started = 0
        self.progress.configure(maximum=len(jobs), value=0)
        self.cancel.clear()
        self.worker = threading.Thread(target=self.work, args=(jobs, skipped))
        self.worker.start()
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
        result = run_jobs(
            jobs, on_start=lambda job: self.events.put(("start", job)), cancel=self.cancel
        )
        self.events.put(("done", result, skipped))

    def poll(self) -> None:
        if self.closing:
            self.poll_shutdown()
            return
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
            elif event[0] == "done":
                self.finish(event[1], event[2])
                return
            else:
                self.finish_merge(event)
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

    # Merging

    def choose_pdfs(self) -> None:
        if self.busy:
            return
        initial = self.pdfs[-1].parent if self.pdfs else Path.home()
        files = filedialog.askopenfilenames(
            parent=self.root, title="Add PDFs", initialdir=initial, filetypes=PDF_FILE_TYPES
        )
        self.add_pdfs(files)

    def add_pdfs(self, files: Iterable[str]) -> None:
        if self.busy:
            return
        added = ignored = 0
        for name in files:
            path = Path(name).expanduser().resolve()
            if path.suffix.lower() != ".pdf" or not path.is_file():
                ignored += 1
            elif path not in self.pdfs:
                self.pdfs.append(path)
                added += 1
        self.refresh_merge_list()
        if ignored:
            kind = "is not a PDF" if ignored == 1 else "are not PDFs"
            self.merge_status.set(f"Ignored {plural(ignored, 'file')} that {kind}.")
        elif added:
            self.merge_status.set(self.merge_hint())

    def merge_hint(self) -> str:
        if not self.pdfs:
            return MERGE_HINT
        return "Add at least one more PDF." if len(self.pdfs) == 1 else ""

    def remove_selected_pdfs(self) -> None:
        if self.busy:
            return
        selected = {Path(item) for item in self.merge_tree.selection()}
        self.pdfs = [path for path in self.pdfs if path not in selected]
        self.refresh_merge_list()
        self.merge_status.set(self.merge_hint())

    def move_selected_pdfs(self, step: int) -> None:
        """Move the selected PDFs one place up (-1) or down (1), keeping their order."""
        if self.busy:
            return
        selected = [Path(item) for item in self.merge_tree.selection()]
        positions = sorted(self.pdfs.index(path) for path in selected)
        if not positions or positions[0] + step < 0 or positions[-1] + step >= len(self.pdfs):
            return
        for position in positions if step < 0 else reversed(positions):
            self.pdfs[position], self.pdfs[position + step] = self.pdfs[position + step], self.pdfs[position]
        self.refresh_merge_list()
        self.merge_tree.selection_set([str(path) for path in selected])
        self.merge_tree.see(str(selected[0]))

    def refresh_merge_list(self) -> None:
        self.merge_tree.delete(*self.merge_tree.get_children())
        for path in self.pdfs:
            self.merge_tree.insert("", "end", iid=str(path), values=(path.name, display_folder(path.parent)))
        self.update_controls()

    def merge(self) -> None:
        if self.busy or len(self.pdfs) < 2:
            return
        first = self.pdfs[0]
        name = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save merged PDF as",
            initialdir=first.parent,
            initialfile=f"{first.stem} merged.pdf",
            defaultextension=".pdf",
            filetypes=PDF_FILE_TYPES,
            # DocZap asks below, about the exact file it will write. Windows and
            # Linux honour this; macOS ignores it and its panel always asks too.
            confirmoverwrite=False,
        )
        if not name:
            return
        output = Path(name)
        if output.suffix.lower() != ".pdf":
            output = output.with_name(f"{output.name}.pdf")
        output = output.parent.resolve() / output.name
        if output.resolve() in self.pdfs:
            messagebox.showerror(
                "Choose another name",
                f"{output.name} is one of the PDFs being merged. Save the merged PDF under another name.",
                parent=self.root,
            )
            return
        # Consent covers only the file the user was asked about. A file that
        # appears later is never replaced, and one that changes is kept.
        existing = file_identity(output)
        if existing is not None and not messagebox.askyesno(
            "Replace existing PDF?",
            f"{output.name} already exists.",
            detail=f"It is in {display_folder(output.parent)}. Replace it?",
            icon=messagebox.WARNING,
            default=messagebox.NO,
            parent=self.root,
        ):
            return

        self.set_busy(True)
        self.merge_status.set(f"Merging {plural(len(self.pdfs), 'PDF')}…")
        self.worker = threading.Thread(target=self.merge_work, args=(list(self.pdfs), output, existing))
        self.worker.start()
        self.root.after(100, self.poll)

    def merge_work(self, pdfs: list[Path], output: Path, replace: FileIdentity | None) -> None:
        # Runs on a background thread, so it only talks to the window through the queue.
        try:
            pages = merge_pdfs(pdfs, output, overwrite=replace is not None, replace_only=replace)
        except FileExistsError:
            message = (
                f"{output.name} was created or changed while DocZap was merging, so it was "
                "left as it is. Merge again to choose what to do."
            )
            self.events.put(("merge failed", message))
        except Exception as exc:
            self.events.put(("merge failed", str(exc)))
        else:
            self.events.put(("merged", output, pages))

    def finish_merge(self, event: tuple) -> None:
        self.set_busy(False)
        if event[0] == "merged":
            output, pages = event[1], event[2]
            self.pdfs = []
            self.refresh_merge_list()
            self.merge_status.set(f"Created {output.name} ({plural(pages, 'page')}).")
            self.merged_output = output
            self.merge_reveal_button.grid()
        else:
            self.merge_status.set("The PDFs were not merged.")
            messagebox.showerror("The PDFs were not merged", event[1], parent=self.root)

    def reveal_merged(self) -> None:
        if self.merged_output is not None:
            system.reveal(self.merged_output)

    # State

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.reveal_button.grid_remove()
            self.merge_reveal_button.grid_remove()
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

        has_pdf_selection = bool(self.merge_tree.selection())
        enable(self.add_pdfs_button, idle)
        enable(self.remove_pdfs_button, idle and has_pdf_selection)
        enable(self.move_up_button, idle and has_pdf_selection)
        enable(self.move_down_button, idle and has_pdf_selection)
        can_merge = idle and len(self.pdfs) >= 2
        enable(self.merge_button, can_merge)
        self.merge_button.configure(default="active" if can_merge else "normal")

    def poll_shutdown(self) -> None:
        # Tk stays responsive until the worker has stopped the renderer and
        # released the profile lock. Never destroy Tk while it is still working.
        if self.worker is not None and self.worker.is_alive():
            self.root.after(50, self.poll_shutdown)
        else:
            self.root.destroy()

    def quit(self) -> None:
        if self.closing:
            return
        if self.busy and not messagebox.askokcancel(
            "Quit DocZap?",
            "DocZap is still working on your files. Quit anyway?",
            icon=messagebox.WARNING,
            parent=self.root,
        ):
            return
        if self.busy:
            self.closing = True
            self.cancel.set()
            self.status.set("Stopping conversion…")
            # The existing poll callback takes over shutdown.
            return
        self.root.destroy()


def main() -> int:
    # The frozen app can convert without opening a window. CI uses this same
    # entry point to verify the renderer and its environment inside each bundle.
    if sys.argv[1:2] == ["--convert"]:
        from doczap.cli import main as convert_main

        return convert_main(sys.argv[2:])
    # macOS passes a -psn_ process serial number when an app is opened from Finder.
    files = [arg for arg in sys.argv[1:] if not arg.startswith("-psn_")]
    system.enable_high_dpi()
    root = tk.Tk()
    App(root, files)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
