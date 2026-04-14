#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Import DownloadManager whether this script is executed as a module inside
# the ifetch package or run directly via `python ifetch/cli.py`.
# ---------------------------------------------------------------------------

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from ifetch.downloader import DownloadManager  # type: ignore
else:
    from .downloader import DownloadManager  # type: ignore


class CliProgressTracker:
    def __init__(self):
        self.total_items = 0
        self.completed_items = 0

    def _pct(self, done: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return (done / total) * 100.0

    def handle_event(self, event):
        name = event.get("name")
        if name == "transfer_session_started":
            self.total_items = int(event.get("total_items", 0))
            self.completed_items = 0
            print(f"[overall] started: 0/{self.total_items} completed")
        elif name == "transfer_item_started":
            print(f"[overall] doing {event.get('index')}/{event.get('total')}: {event.get('item_name')}")
        elif name == "transfer_item_stage":
            print(f"[item] {event.get('item_name')}: {event.get('stage')}")
        elif name == "download_progress":
            done = int(event.get("downloaded", 0))
            total = int(event.get("total_size", 0))
            print(f"[download] {event.get('remote_item_name')}: {self._pct(done, total):.1f}% ({done}/{total} bytes)")
        elif name == "upload_progress":
            done = int(event.get("uploaded", 0))
            total = int(event.get("total_size", 0))
            print(f"[upload] {event.get('file_name')}: {self._pct(done, total):.1f}% ({done}/{total} bytes)")
        elif name == "transfer_item_completed":
            self.completed_items += 1
            overall_pct = self._pct(self.completed_items, max(self.total_items, 1))
            print(f"[overall] done {self.completed_items}/{self.total_items} ({overall_pct:.1f}%): {event.get('item_name')}")
        elif name == "transfer_session_completed":
            print("[overall] all selected items transferred")


def parse_selection(selection: Optional[str], max_items: int) -> List[int]:
    if max_items <= 0:
        return []

    if not selection or selection.strip() == "":
        raw = input(f"Select item numbers to transfer (e.g. 1,3,5 or 'all') [1-{max_items}]: ").strip()
    else:
        raw = selection.strip()

    if raw.lower() == "all":
        return list(range(max_items))

    out = []
    for part in raw.split(","):
        token = part.strip()
        if not token.isdigit():
            raise ValueError(f"Invalid selection token: '{token}'")
        idx = int(token)
        if idx < 1 or idx > max_items:
            raise ValueError(f"Selection out of range: {idx}")
        out.append(idx - 1)
    return sorted(set(out))


def run_transfer_to_gdrive(args, downloader):
    if __package__ in (None, ""):
        from ifetch.gdrive_uploader import GoogleDriveUploader  # type: ignore
        from ifetch.transfer import TransferOrchestrator  # type: ignore
    else:
        from .gdrive_uploader import GoogleDriveUploader  # type: ignore
        from .transfer import TransferOrchestrator  # type: ignore

    progress = CliProgressTracker()
    downloader.set_progress_callback(progress.handle_event)

    uploader = GoogleDriveUploader(
        credentials_file=args.gdrive_credentials,
        token_file=args.gdrive_token,
        folder_id=args.gdrive_folder_id,
        progress_callback=progress.handle_event,
    )
    orchestrator = TransferOrchestrator(
        downloader=downloader,
        uploader=uploader,
        progress_callback=progress.handle_event,
    )

    selectable = orchestrator.list_selectable_items(args.icloud_path)
    if not selectable:
        print("No selectable items found at the provided iCloud path.")
        return

    print("\nSelectable items:")
    for idx, item in enumerate(selectable, start=1):
        size_info = f", {item.size} bytes" if item.item_type == "file" else ""
        print(f"  {idx}. [{item.item_type}] {item.name}{size_info}")

    picked_indexes = parse_selection(args.select_items, len(selectable))
    selected_items = [selectable[i] for i in picked_indexes]
    if not selected_items:
        print("No items selected; nothing to transfer.")
        return

    print(f"\nSelected {len(selected_items)} item(s). Starting sequential transfer...")
    temp_dir = Path(args.local_path).expanduser().resolve()
    orchestrator.transfer_selected(selected_items, temp_dir)


def main():
    parser = argparse.ArgumentParser(
        description='Sync files/folders from iCloud Drive locally with resume, diff, and parallel downloads.'
    )
    parser.add_argument(
        'icloud_path',
        nargs='?',
        default=None,
        help='Remote iCloud Drive path (e.g., "Documents/MyFolder"). Required unless --list-shared is supplied.'
    )
    parser.add_argument(
        'local_path',
        nargs='?',
        default='.',
        help='Local destination directory (default: current directory)'
    )
    parser.add_argument(
        '--email',
        help='iCloud account email (can also use ICLOUD_EMAIL environment variable)'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum number of concurrent downloads (default: 4)'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Maximum number of retry attempts for failed chunks (default: 3)'
    )
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=1024 * 1024,
        help='Chunk size in bytes for differential downloads (default: 1MB)'
    )
    parser.add_argument(
        '--log-file',
        help='Path to a file to save structured JSON logs'
    )
    parser.add_argument(
        '--list',
        dest='list_only',
        action='store_true',
        help='List directory contents instead of downloading'
    )
    parser.add_argument(
        '--list-shared',
        dest='list_shared',
        action='store_true',
        help='List top-level items that have been shared with you'
    )
    parser.add_argument(
        '--profile',
        help='Profile name from ~/.ifetch_profiles.json to use for include/exclude patterns'
    )
    parser.add_argument(
        '--profile-file',
        dest='profile_file',
        help='Custom path to a profile JSON file (overrides default ~/.ifetch_profiles.json)'
    )
    parser.add_argument(
        '--enable-plugins',
        action='store_true',
        help='Enable plugin loading (disabled by default for safety)'
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Launch the GUI interface for item selection and transfer progress'
    )
    parser.add_argument(
        '--transfer-to-gdrive',
        action='store_true',
        help='Transfer selected iCloud items to Google Drive sequentially'
    )
    parser.add_argument(
        '--gdrive-credentials',
        default='client_secrets.json',
        help='Path to Google OAuth client credentials JSON (default: ./client_secrets.json)'
    )
    parser.add_argument(
        '--gdrive-token',
        default=str(Path.home() / '.ifetch_gdrive_token.json'),
        help='Path to store Google OAuth token JSON (default: ~/.ifetch_gdrive_token.json)'
    )
    parser.add_argument(
        '--gdrive-folder-id',
        help='Optional target Google Drive folder ID'
    )
    parser.add_argument(
        '--select-items',
        help='Comma-separated 1-based indices to transfer in --transfer-to-gdrive mode, or "all"'
    )

    args = parser.parse_args()

    try:
        if args.gui:
            if __package__ in (None, ""):
                from ifetch.gui import launch_gui  # type: ignore
            else:
                from .gui import launch_gui  # type: ignore
            launch_gui()
            return

        print("=" * 70)
        print("iCloud Drive Downloader")
        if args.icloud_path:
            print(f"Remote Path: {args.icloud_path}")
        print(f"Local Path: {args.local_path}")
        print(f"Parallel Workers: {args.max_workers}")
        print("=" * 70)

        from ifetch.profiles import ProfileManager

        pm = None
        if args.profile:
            cfg_path = Path(args.profile_file).expanduser() if args.profile_file else None
            pm = ProfileManager(args.profile, config_path=cfg_path)  # type: ignore[arg-type]
        include_pats, exclude_pats = pm.get_patterns() if pm else ([], [])

        downloader = DownloadManager(
            email=args.email,
            max_workers=args.max_workers,
            max_retries=args.max_retries,
            chunk_size=args.chunk_size,
            include_patterns=include_pats,
            exclude_patterns=exclude_pats,
            enable_plugins=args.enable_plugins,
        )

        print("Authenticating with iCloud...")
        downloader.authenticate()
        print("Authentication successful!")

        if args.transfer_to_gdrive:
            if not args.icloud_path:
                raise ValueError("icloud_path is required for --transfer-to-gdrive")
            run_transfer_to_gdrive(args, downloader)
            print("\nOperation completed.")
            return

        if args.list_shared:
            print("\nListing top-level shared items:")
            print("-" * 50)
            downloader.list_shared_roots()
        elif args.list_only:
            print(f"\nListing contents of '{args.icloud_path}':")
            print("-" * 50)
            downloader.list_contents(args.icloud_path)
        else:
            if not args.icloud_path:
                raise ValueError("icloud_path is required unless using --list-shared")
            print(f"\nDownloading from '{args.icloud_path}' to '{args.local_path}'")
            print("This may take some time depending on the size of the content...")
            downloader.download(
                args.icloud_path,
                args.local_path,
                log_file=args.log_file
            )

            summary = downloader.generate_summary_report()["summary"]
            print("\nDownload Summary:")
            print(f"- Total files: {summary['total_files']}")
            print(f"- Successfully downloaded: {summary['successful']}")
            print(f"- Failed: {summary['failed']}")
            print(f"- Total data transferred: {summary['total_bytes_transferred'] / (1024 * 1024):.2f} MB")
            print(f"- Changed chunks: {summary['total_changed_chunks']}")
            print(f"\nDetailed report saved to '{args.local_path}/download_report.json'")

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nOperation completed.")


if __name__ == '__main__':
    main()
