import queue
import threading
from pathlib import Path
from typing import Any, Dict, List

import tkinter as tk
from tkinter import ttk, messagebox

from .downloader import DownloadManager
from .gdrive_uploader import GoogleDriveUploader
from .transfer import TransferOrchestrator, SelectableItem


class TransferGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("iFetch iCloud -> Google Drive Transfer")
        self.root.geometry("980x680")

        self.events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.downloader: DownloadManager | None = None
        self.items: List[SelectableItem] = []
        self.total_items = 0
        self.completed_items = 0

        self._build_ui()
        self.root.after(100, self._drain_events)

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        self.email_var = tk.StringVar()
        self.icloud_path_var = tk.StringVar(value="/")
        self.temp_dir_var = tk.StringVar(value=str(Path.cwd() / "ifetch_temp"))
        self.credentials_var = tk.StringVar(value=str(Path.cwd() / "client_secrets.json"))
        self.token_var = tk.StringVar(value=str(Path.home() / ".ifetch_gdrive_token.json"))
        self.gdrive_folder_var = tk.StringVar()

        inputs = [
            ("iCloud Email", self.email_var),
            ("iCloud Base Path", self.icloud_path_var),
            ("Temp Download Dir", self.temp_dir_var),
            ("Google Credentials JSON", self.credentials_var),
            ("Google Token JSON", self.token_var),
            ("Google Drive Folder ID (optional)", self.gdrive_folder_var),
        ]
        for idx, (label, var) in enumerate(inputs):
            ttk.Label(frm, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(frm, textvariable=var, width=95).grid(row=idx, column=1, sticky="ew", pady=4)

        btns = ttk.Frame(frm)
        btns.grid(row=len(inputs), column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(btns, text="1) Authenticate iCloud", command=self.authenticate).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text="2) Load Items", command=self.load_items).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text="3) Start Transfer", command=self.start_transfer).pack(side=tk.LEFT)

        ttk.Label(frm, text="Select items to transfer:").grid(row=len(inputs) + 1, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.items_list = tk.Listbox(frm, selectmode=tk.EXTENDED, height=14)
        self.items_list.grid(row=len(inputs) + 2, column=0, columnspan=2, sticky="nsew")

        self.current_var = tk.StringVar(value="Current: idle")
        ttk.Label(frm, textvariable=self.current_var).grid(row=len(inputs) + 3, column=0, columnspan=2, sticky="w", pady=(10, 4))

        ttk.Label(frm, text="Current file download progress").grid(row=len(inputs) + 4, column=0, columnspan=2, sticky="w")
        self.download_pb = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.download_pb.grid(row=len(inputs) + 5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(frm, text="Current file upload progress").grid(row=len(inputs) + 6, column=0, columnspan=2, sticky="w")
        self.upload_pb = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.upload_pb.grid(row=len(inputs) + 7, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(frm, text="Whole process progress").grid(row=len(inputs) + 8, column=0, columnspan=2, sticky="w")
        self.overall_pb = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.overall_pb.grid(row=len(inputs) + 9, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.log = tk.Text(frm, height=11)
        self.log.grid(row=len(inputs) + 10, column=0, columnspan=2, sticky="nsew")

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(len(inputs) + 2, weight=1)
        frm.rowconfigure(len(inputs) + 10, weight=1)

    def _append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def _emit(self, evt: Dict[str, Any]) -> None:
        self.events.put(evt)

    def authenticate(self) -> None:
        email = self.email_var.get().strip()
        if not email:
            messagebox.showerror("Missing input", "Please enter iCloud email.")
            return
        self.downloader = DownloadManager(email=email)
        self.downloader.set_progress_callback(self._emit)
        try:
            self.downloader.authenticate()
            self._append_log("✓ Authenticated with iCloud.")
            messagebox.showinfo("Success", "iCloud authentication successful.")
        except Exception as e:
            messagebox.showerror("Authentication failed", str(e))

    def load_items(self) -> None:
        if not self.downloader:
            messagebox.showerror("Not ready", "Authenticate iCloud first.")
            return
        base_path = self.icloud_path_var.get().strip() or "/"
        try:
            orchestrator = TransferOrchestrator(
                self.downloader,
                GoogleDriveUploader(
                    credentials_file=self.credentials_var.get().strip(),
                    token_file=self.token_var.get().strip(),
                    folder_id=self.gdrive_folder_var.get().strip() or None,
                    progress_callback=self._emit,
                ),
                progress_callback=self._emit,
            )
            self.items = orchestrator.list_selectable_items(base_path)
            self.items_list.delete(0, tk.END)
            for item in self.items:
                label = f"[{item.item_type}] {item.name}"
                self.items_list.insert(tk.END, label)
            self._append_log(f"Loaded {len(self.items)} selectable item(s) from '{base_path}'.")
        except Exception as e:
            messagebox.showerror("Load items failed", str(e))

    def start_transfer(self) -> None:
        if not self.downloader:
            messagebox.showerror("Not ready", "Authenticate iCloud first.")
            return
        indices = list(self.items_list.curselection())
        if not indices:
            messagebox.showerror("No selection", "Select at least one item.")
            return

        selected = [self.items[i] for i in indices]
        self.total_items = len(selected)
        self.completed_items = 0
        self.overall_pb["value"] = 0
        self.download_pb["value"] = 0
        self.upload_pb["value"] = 0

        uploader = GoogleDriveUploader(
            credentials_file=self.credentials_var.get().strip(),
            token_file=self.token_var.get().strip(),
            folder_id=self.gdrive_folder_var.get().strip() or None,
            progress_callback=self._emit,
        )
        orchestrator = TransferOrchestrator(self.downloader, uploader, progress_callback=self._emit)
        self.downloader.set_progress_callback(self._emit)

        temp_dir = Path(self.temp_dir_var.get().strip() or "ifetch_temp")

        def _run() -> None:
            try:
                orchestrator.transfer_selected(selected, temp_dir)
                self._emit({"name": "gui_transfer_done"})
            except Exception as exc:
                self._emit({"name": "gui_transfer_error", "error": str(exc)})

        threading.Thread(target=_run, daemon=True).start()
        self._append_log("Transfer started.")

    def _drain_events(self) -> None:
        while True:
            try:
                evt = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(evt)
        self.root.after(100, self._drain_events)

    def _handle_event(self, evt: Dict[str, Any]) -> None:
        name = evt.get("name", "")
        if name == "download_progress":
            total = max(int(evt.get("total_size", 0)), 1)
            done = int(evt.get("downloaded", 0))
            self.download_pb["value"] = min(100, (done / total) * 100)
            self.current_var.set(f"Current: downloading {evt.get('remote_item_name', '')}")
        elif name == "upload_progress":
            total = max(int(evt.get("total_size", 0)), 1)
            done = int(evt.get("uploaded", 0))
            self.upload_pb["value"] = min(100, (done / total) * 100)
            self.current_var.set(f"Current: uploading {evt.get('file_name', '')}")
        elif name == "transfer_item_stage":
            self._append_log(f"[{evt.get('index')}/{evt.get('total')}] {evt.get('item_name')}: {evt.get('stage')}")
        elif name == "transfer_item_completed":
            self.completed_items += 1
            self.overall_pb["value"] = (self.completed_items / max(self.total_items, 1)) * 100
            self.download_pb["value"] = 0
            self.upload_pb["value"] = 0
            self._append_log(f"✓ Completed: {evt.get('item_name')}")
            self.current_var.set("Current: waiting for next item")
        elif name == "gui_transfer_done":
            self.current_var.set("Current: completed")
            self._append_log("All selected items transferred.")
            messagebox.showinfo("Done", "Transfer completed.")
        elif name == "gui_transfer_error":
            self.current_var.set("Current: error")
            self._append_log(f"Error: {evt.get('error')}")
            messagebox.showerror("Transfer failed", str(evt.get("error")))


def launch_gui() -> None:
    root = tk.Tk()
    TransferGUI(root)
    root.mainloop()
