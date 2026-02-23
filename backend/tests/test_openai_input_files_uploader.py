import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_integration.openai_input_files_uploader import upload_input_files_once


def test_upload_input_files_once_writes_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "input_files"
    source_dir.mkdir()
    (source_dir / "folder").mkdir()
    (source_dir / "folder" / "a.md").write_text("A", encoding="utf-8")
    (source_dir / "folder" / "b.txt").write_text("B", encoding="utf-8")
    (source_dir / "skip.png").write_text("X", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"

    class FakeFiles:
        def __init__(self) -> None:
            self.created_files: list[str] = []
            self.counter = 0

        def create(self, *, file, purpose: str):  # noqa: ANN001
            assert purpose == "assistants"
            self.created_files.append(file[0])
            self.counter += 1
            return SimpleNamespace(id=f"file_{self.counter}")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = FakeFiles()

    monkeypatch.setattr("openai_integration.openai_input_files_uploader.OpenAI", FakeOpenAI)

    result = upload_input_files_once(
        input_files_dir=source_dir,
        manifest_path=manifest_path,
        env_file=env_file,
    )

    assert result.uploaded_count == 2
    assert result.manifest_path == manifest_path

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["input_files_dir"] == str(source_dir.resolve())
    assert [item["relative_path"] for item in payload["files"]] == [
        "folder/a.md",
        "folder/b.txt",
    ]
    assert [item["file_id"] for item in payload["files"]] == ["file_1", "file_2"]


def test_upload_input_files_once_rejects_empty_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "empty"
    source_dir.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No supported files"):
        upload_input_files_once(
            input_files_dir=source_dir,
            manifest_path=tmp_path / "manifest.json",
            env_file=env_file,
        )
