import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_integration.openai_input_files_uploader import upload_input_files_once


def test_upload_input_files_once_writes_manifest_and_preserves_rag_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_files_dir = tmp_path / "input_files"
    input_files_dir.mkdir()
    (input_files_dir / "folder").mkdir()
    (input_files_dir / "folder" / "a.md").write_text("A", encoding="utf-8")

    existing_manifest = {
        "version": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "input_files_dir": "/old/input",
        "rag_files_dir": "/tmp/rag",
        "input_files": [],
        "rag_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "rag_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(existing_manifest), encoding="utf-8")

    class FakeFiles:
        def __init__(self) -> None:
            self.created_files: list[str] = []
            self.counter = 0

        def create(self, *, file, purpose: str):  # noqa: ANN001
            assert purpose == "assistants"
            self.created_files.append(file[0])
            self.counter += 1
            return SimpleNamespace(id=f"input_file_{self.counter}")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = FakeFiles()

    monkeypatch.setattr("openai_integration.openai_input_files_uploader.OpenAI", FakeOpenAI)

    result = upload_input_files_once(
        input_files_dir=input_files_dir,
        manifest_path=manifest_path,
        env_file=env_file,
    )

    assert result.input_uploaded_count == 1
    assert result.manifest_path == manifest_path

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["input_files_dir"] == str(input_files_dir.resolve())
    assert payload["rag_files_dir"] == "/tmp/rag"
    assert [item["relative_path"] for item in payload["input_files"]] == ["folder/a.md"]
    assert payload["rag_files"][0]["file_id"] == "rag_file_1"


def test_upload_input_files_once_rejects_empty_input_dir(tmp_path: Path) -> None:
    input_files_dir = tmp_path / "empty"
    input_files_dir.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No supported files found under input_files_dir"):
        upload_input_files_once(
            input_files_dir=input_files_dir,
            manifest_path=tmp_path / "manifest.json",
            env_file=env_file,
        )
