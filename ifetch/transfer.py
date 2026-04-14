import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .downloader import DownloadManager
from .gdrive_uploader import GoogleDriveUploader
from .utils import can_read_file


@dataclass
class SelectableItem:
    name: str
    item_type: str
    full_path: str
    size: int = 0


class TransferOrchestrator:
    """Sequential iCloud -> local -> Google Drive transfer manager."""

    def __init__(
        self,
        downloader: DownloadManager,
        uploader: GoogleDriveUploader,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.downloader = downloader
        self.uploader = uploader
        self.progress_callback = progress_callback

    def _emit(self, name: str, **kwargs: Any) -> None:
        if self.progress_callback:
            self.progress_callback({"name": name, **kwargs})

    def list_selectable_items(self, base_path: str) -> List[SelectableItem]:
        root = self.downloader.get_drive_item(base_path)
        if not hasattr(root, "dir"):
            return []

        items = []
        normalized_base = base_path.strip("/")
        for child_name in root.dir():
            child = root[child_name]
            child_type = "file" if can_read_file(child) else "folder"
            child_path = f"{normalized_base}/{child_name}" if normalized_base else child_name
            items.append(
                SelectableItem(
                    name=child_name,
                    item_type=child_type,
                    full_path=child_path,
                    size=getattr(child, "size", 0) if child_type == "file" else 0,
                )
            )
        return sorted(items, key=lambda i: i.name.lower())

    def transfer_selected(self, selected_items: List[SelectableItem], temp_dir: Path) -> None:
        temp_dir = temp_dir.resolve()
        temp_dir.mkdir(parents=True, exist_ok=True)
        total = len(selected_items)
        self._emit("transfer_session_started", total_items=total, temp_dir=str(temp_dir))

        for idx, sel in enumerate(selected_items, start=1):
            local_target = (temp_dir / sel.name).resolve()
            if temp_dir not in local_target.parents and local_target != temp_dir:
                raise ValueError(f"Unsafe local target path: {local_target}")

            self._emit(
                "transfer_item_started",
                index=idx,
                total=total,
                item_name=sel.name,
                item_type=sel.item_type,
                remote_path=sel.full_path,
                local_path=str(local_target),
            )

            self._emit("transfer_item_stage", stage="downloading", item_name=sel.name, index=idx, total=total)
            self.downloader.download(sel.full_path, local_target)

            self._emit("transfer_item_stage", stage="uploading", item_name=sel.name, index=idx, total=total)
            self.uploader.upload_path(local_target)

            self._emit("transfer_item_stage", stage="cleaning_up", item_name=sel.name, index=idx, total=total)
            if local_target.is_dir():
                shutil.rmtree(local_target, ignore_errors=True)
            elif local_target.exists():
                local_target.unlink()

            self._emit("transfer_item_completed", index=idx, total=total, item_name=sel.name)

        self._emit("transfer_session_completed", total_items=total)
