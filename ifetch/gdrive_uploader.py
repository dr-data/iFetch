import json
from pathlib import Path
from typing import Callable, Dict, Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class GoogleDriveUploader:
    """Google Drive uploader with resumable progress callbacks."""

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(
        self,
        credentials_file: str,
        token_file: str,
        folder_id: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.folder_id = folder_id
        self.progress_callback = progress_callback
        self.service = None

    def _emit(self, name: str, **kwargs: Any) -> None:
        if self.progress_callback:
            self.progress_callback({"name": name, **kwargs})

    def authenticate(self) -> None:
        token_path = Path(self.token_file)
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self.service = build("drive", "v3", credentials=creds)
        self._emit("upload_auth_completed")

    def _ensure_service(self) -> None:
        if self.service is None:
            self.authenticate()

    def create_folder(self, name: str, parent_id: Optional[str]) -> str:
        self._ensure_service()
        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = self.service.files().create(  # type: ignore[union-attr]
            body=metadata,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
        return folder["id"]

    def upload_file(self, local_file: Path, parent_id: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_service()
        file_size = local_file.stat().st_size
        metadata: Dict[str, Any] = {"name": local_file.name}
        target_parent = parent_id or self.folder_id
        if target_parent:
            metadata["parents"] = [target_parent]

        media = MediaFileUpload(str(local_file), resumable=True)
        request = self.service.files().create(  # type: ignore[union-attr]
            body=metadata,
            media_body=media,
            fields="id,name,size",
            supportsAllDrives=True,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status is not None:
                uploaded = int(status.progress() * file_size)
                self._emit(
                    "upload_progress",
                    file_name=local_file.name,
                    local_path=str(local_file),
                    uploaded=uploaded,
                    total_size=file_size,
                )

        self._emit(
            "upload_file_completed",
            file_name=local_file.name,
            local_path=str(local_file),
            total_size=file_size,
            file_id=response.get("id"),
        )
        return response

    def upload_path(self, local_path: Path, parent_id: Optional[str] = None) -> None:
        if local_path.is_file():
            self.upload_file(local_path, parent_id)
            return

        folder_id = self.create_folder(local_path.name, parent_id or self.folder_id)
        for child in sorted(local_path.iterdir(), key=lambda p: p.name.lower()):
            self.upload_path(child, folder_id)
