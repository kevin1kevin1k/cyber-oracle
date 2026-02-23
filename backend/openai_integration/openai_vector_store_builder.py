from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from openai import OpenAI

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "input_files_manifest.json"
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


@dataclass
class BuildVectorStoreResult:
    vector_store_id: str
    rag_files_dir: Path
    file_count: int
    uploaded_file_count: int
    dry_run: bool
    manifest_path: Path


def iter_supported_files(rag_files_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in rag_files_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return sorted(files)


def _normalize_relative_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./")


def _read_env_map(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}
    values = dotenv_values(env_file)
    return {key: value for key, value in values.items() if value is not None}


def upsert_env_key(env_file: Path, key: str, value: str) -> None:
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = content.splitlines()

    new_line = f"{key}={value}"
    replaced = False
    updated_lines: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            updated_lines.append(new_line)
            replaced = True
        else:
            updated_lines.append(line)

    if not replaced:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(new_line)

    env_file.write_text("\n".join(updated_lines).strip() + "\n", encoding="utf-8")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _extract_manifest_entries(entries: Any, field_name: str) -> list[dict[str, str]]:
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ValueError(f"Manifest {field_name} must be a list")

    parsed: list[dict[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError(f"Manifest {field_name} entry must be object")
        relative_path = item.get("relative_path")
        file_id = item.get("file_id")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(f"Manifest {field_name} entry missing relative_path")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError(f"Manifest {field_name} entry missing file_id")

        parsed.append(
            {
                "relative_path": _normalize_relative_path(relative_path),
                "filename": _normalize_relative_path(
                    item.get("filename") if isinstance(item.get("filename"), str) else relative_path
                ),
                "file_id": file_id.strip(),
                "uploaded_at": (
                    item.get("uploaded_at")
                    if isinstance(item.get("uploaded_at"), str) and item.get("uploaded_at")
                    else ""
                ),
            }
        )
    return parsed


def _read_manifest_payload(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {
            "version": 2,
            "input_files": [],
            "rag_files": [],
        }

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Manifest root must be object")
    return payload


def _upsert_rag_files_manifest(
    *,
    manifest_path: Path,
    rag_files_dir: Path,
    rag_entries: list[dict[str, str]],
    uploaded_at: str,
) -> None:
    payload = _read_manifest_payload(manifest_path)
    input_entries = _extract_manifest_entries(payload.get("input_files"), "input_files")

    merged = {
        "version": 2,
        "created_at": uploaded_at,
        "input_files_dir": payload.get("input_files_dir"),
        "rag_files_dir": str(rag_files_dir.resolve()),
        "input_files": input_entries,
        "rag_files": rag_entries,
    }
    _atomic_write_text(manifest_path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")


def build_vector_store(
    *,
    rag_files_dir: Path,
    vector_store_name: str,
    env_file: Path,
    manifest_path: Path,
    recreate: bool,
    dry_run: bool,
) -> BuildVectorStoreResult:
    if not rag_files_dir.exists():
        raise ValueError(f"RAG files directory does not exist: {rag_files_dir}")
    if not rag_files_dir.is_dir():
        raise ValueError(f"RAG files path is not a directory: {rag_files_dir}")

    files = iter_supported_files(rag_files_dir)
    if not files:
        raise ValueError(f"No supported files found under: {rag_files_dir}")

    if dry_run:
        return BuildVectorStoreResult(
            vector_store_id="dry-run",
            rag_files_dir=rag_files_dir,
            file_count=len(files),
            uploaded_file_count=0,
            dry_run=True,
            manifest_path=manifest_path,
        )

    env_map = _read_env_map(env_file)
    api_key = env_map.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")

    client = OpenAI(api_key=api_key)
    existing_store_id = env_map.get("VECTOR_STORE_ID")
    if recreate and existing_store_id:
        try:
            client.vector_stores.delete(existing_store_id)
        except Exception:
            pass
        existing_store_id = None

    if existing_store_id and not recreate:
        vector_store_id = existing_store_id
    else:
        store = client.vector_stores.create(name=vector_store_name)
        vector_store_id = store.id

    uploaded_at = datetime.now(UTC).isoformat()
    uploaded_count = 0
    rag_entries: list[dict[str, str]] = []

    for path in files:
        relative_path = _normalize_relative_path(path.relative_to(rag_files_dir).as_posix())
        with path.open("rb") as file_stream:
            file_object = client.files.create(
                file=(relative_path, file_stream),
                purpose="assistants",
            )
        client.vector_stores.files.create_and_poll(
            vector_store_id=vector_store_id,
            file_id=file_object.id,
        )
        uploaded_count += 1
        rag_entries.append(
            {
                "relative_path": relative_path,
                "filename": relative_path,
                "file_id": file_object.id,
                "uploaded_at": uploaded_at,
            }
        )

    upsert_env_key(env_file, "VECTOR_STORE_ID", vector_store_id)
    _upsert_rag_files_manifest(
        manifest_path=manifest_path,
        rag_files_dir=rag_files_dir,
        rag_entries=rag_entries,
        uploaded_at=uploaded_at,
    )

    return BuildVectorStoreResult(
        vector_store_id=vector_store_id,
        rag_files_dir=rag_files_dir,
        file_count=len(files),
        uploaded_file_count=uploaded_count,
        dry_run=False,
        manifest_path=manifest_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build OpenAI vector store from files under backend/cyber oracle",
    )
    parser.add_argument(
        "--rag-files-dir",
        required=True,
        help="Directory containing RAG files used to build vector store",
    )
    parser.add_argument(
        "--vector-store-name",
        default="cyber-oracle-knowledge",
        help="Vector store name for newly created store",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Env file path to persist VECTOR_STORE_ID",
    )
    parser.add_argument(
        "--manifest-path",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Manifest path to write rag_files mapping",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing VECTOR_STORE_ID store and recreate from scratch",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidate files only without calling OpenAI API",
    )
    args = parser.parse_args()

    rag_files_dir = Path(args.rag_files_dir).resolve()
    env_file = Path(args.env_file).resolve()
    manifest_path = Path(args.manifest_path).resolve()
    result = build_vector_store(
        rag_files_dir=rag_files_dir,
        vector_store_name=args.vector_store_name,
        env_file=env_file,
        manifest_path=manifest_path,
        recreate=args.recreate,
        dry_run=args.dry_run,
    )
    print(f"rag_files_dir={result.rag_files_dir}")
    print(f"manifest_path={result.manifest_path}")
    print(f"file_count={result.file_count}")
    print(f"uploaded_file_count={result.uploaded_file_count}")
    print(f"vector_store_id={result.vector_store_id}")
    print(f"dry_run={result.dry_run}")


if __name__ == "__main__":
    main()
