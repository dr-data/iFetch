import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from ifetch.transfer import TransferOrchestrator, SelectableItem  # noqa: E402


class _FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, remote_path, local_path):
        self.calls.append((remote_path, str(local_path)))
        local_path = Path(local_path)
        if remote_path.endswith("Folder"):
            (local_path / "file.txt").parent.mkdir(parents=True, exist_ok=True)
            (local_path / "file.txt").write_text("folder")
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text("file")


class _FakeUploader:
    def __init__(self):
        self.uploaded = []

    def upload_path(self, local_path):
        self.uploaded.append(str(local_path))


def test_transfer_selected_sequential_and_cleanup(tmp_path):
    downloader = _FakeDownloader()
    uploader = _FakeUploader()
    events = []

    orch = TransferOrchestrator(
        downloader=downloader,  # type: ignore[arg-type]
        uploader=uploader,  # type: ignore[arg-type]
        progress_callback=lambda e: events.append(e["name"]),
    )

    selected = [
        SelectableItem(name="A.txt", item_type="file", full_path="Docs/A.txt", size=1),
        SelectableItem(name="Folder", item_type="folder", full_path="Docs/Folder", size=0),
    ]

    orch.transfer_selected(selected, tmp_path)

    assert downloader.calls[0][0] == "Docs/A.txt"
    assert downloader.calls[1][0] == "Docs/Folder"
    assert len(uploader.uploaded) == 2
    assert not (tmp_path / "A.txt").exists()
    assert not (tmp_path / "Folder").exists()
    assert "transfer_session_started" in events
    assert "transfer_session_completed" in events
