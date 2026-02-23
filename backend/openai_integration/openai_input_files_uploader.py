from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "input_files_manifest.json"


@dataclass
class UploadedManifestEntry:
    relative_path: str
    filename: str
    file_id: str
    uploaded_at: str


@dataclass
class UploadInputFilesResult:
    input_files_dir: Path
    manifest_path: Path
    uploaded_count: int


def _normalize_relative_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./")


def _read_openai_api_key(env_file: Path) -> str:
    if not env_file.exists():
        raise ValueError(f"Env file does not exist: {env_file}")

    values = dotenv_values(env_file)
    api_key = values.get("OPENAI_API_KEY")
    if api_key is None or not api_key.strip():
        raise ValueError("OPENAI_API_KEY is required")
    return api_key.strip()


def iter_supported_files(source_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return sorted(files)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def upload_input_files_once(
    *,
    input_files_dir: Path,
    manifest_path: Path,
    env_file: Path,
) -> UploadInputFilesResult:
    if not input_files_dir.exists():
        raise ValueError(f"input_files_dir does not exist: {input_files_dir}")
    if not input_files_dir.is_dir():
        raise ValueError(f"input_files_dir is not a directory: {input_files_dir}")

    files = iter_supported_files(input_files_dir)
    if not files:
        raise ValueError(f"No supported files found under: {input_files_dir}")

    api_key = _read_openai_api_key(env_file)
    client = OpenAI(api_key=api_key)

    uploaded_entries: list[UploadedManifestEntry] = []
    uploaded_at = datetime.now(UTC).isoformat()
    for path in files:
        relative_path = _normalize_relative_path(path.relative_to(input_files_dir).as_posix())
        with path.open("rb") as file_stream:
            file_object = client.files.create(
                file=(relative_path, file_stream),
                purpose="assistants",
            )
        uploaded_entries.append(
            UploadedManifestEntry(
                relative_path=relative_path,
                filename=relative_path,
                file_id=file_object.id,
                uploaded_at=uploaded_at,
            )
        )

    payload = {
        "version": 1,
        "created_at": uploaded_at,
        "input_files_dir": str(input_files_dir.resolve()),
        "files": [
            {
                "relative_path": item.relative_path,
                "filename": item.filename,
                "file_id": item.file_id,
                "uploaded_at": item.uploaded_at,
            }
            for item in uploaded_entries
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(manifest_path, serialized)

    return UploadInputFilesResult(
        input_files_dir=input_files_dir,
        manifest_path=manifest_path,
        uploaded_count=len(uploaded_entries),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload input files once and persist path->file_id mapping into manifest",
    )
    parser.add_argument(
        "--input-files-dir",
        required=True,
        help="Directory of files to upload for future file-search requests",
    )
    parser.add_argument(
        "--manifest-path",
        default=str(DEFAULT_MANIFEST_PATH),
        help="JSON manifest path for uploaded file ids",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Env file path containing OPENAI_API_KEY",
    )
    args = parser.parse_args()

    result = upload_input_files_once(
        input_files_dir=Path(args.input_files_dir).resolve(),
        manifest_path=Path(args.manifest_path).resolve(),
        env_file=Path(args.env_file).resolve(),
    )

    print(f"input_files_dir={result.input_files_dir}")
    print(f"manifest_path={result.manifest_path}")
    print(f"uploaded_count={result.uploaded_count}")


if __name__ == "__main__":
    main()
