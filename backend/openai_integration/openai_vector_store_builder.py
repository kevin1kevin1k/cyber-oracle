from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


@dataclass
class BuildVectorStoreResult:
    vector_store_id: str
    source_dir: Path
    file_count: int
    uploaded_file_count: int
    dry_run: bool


def iter_supported_files(source_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_dir.rglob("*"):
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


def build_vector_store(
    *,
    source_dir: Path,
    vector_store_name: str,
    env_file: Path,
    recreate: bool,
    dry_run: bool,
) -> BuildVectorStoreResult:
    if not source_dir.exists():
        raise ValueError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise ValueError(f"Source path is not a directory: {source_dir}")

    files = iter_supported_files(source_dir)
    if not files:
        raise ValueError(f"No supported files found under: {source_dir}")

    if dry_run:
        return BuildVectorStoreResult(
            vector_store_id="dry-run",
            source_dir=source_dir,
            file_count=len(files),
            uploaded_file_count=0,
            dry_run=True,
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

    uploaded_count = 0
    for path in files:
        relative_path = _normalize_relative_path(path.relative_to(source_dir).as_posix())
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

    upsert_env_key(env_file, "VECTOR_STORE_ID", vector_store_id)
    return BuildVectorStoreResult(
        vector_store_id=vector_store_id,
        source_dir=source_dir,
        file_count=len(files),
        uploaded_file_count=uploaded_count,
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build OpenAI vector store from files under backend/cyber oracle",
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Directory containing knowledge files",
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

    source_dir = Path(args.source_dir).resolve()
    env_file = Path(args.env_file).resolve()
    result = build_vector_store(
        source_dir=source_dir,
        vector_store_name=args.vector_store_name,
        env_file=env_file,
        recreate=args.recreate,
        dry_run=args.dry_run,
    )
    print(f"source_dir={result.source_dir}")
    print(f"file_count={result.file_count}")
    print(f"uploaded_file_count={result.uploaded_file_count}")
    print(f"vector_store_id={result.vector_store_id}")
    print(f"dry_run={result.dry_run}")


if __name__ == "__main__":
    main()
