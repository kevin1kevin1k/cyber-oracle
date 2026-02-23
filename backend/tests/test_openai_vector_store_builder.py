import json
from pathlib import Path
from types import SimpleNamespace

from openai_integration.openai_vector_store_builder import (
    BuildVectorStoreResult,
    build_vector_store,
    iter_supported_files,
    upsert_env_key,
)


def test_iter_supported_files_filters_extensions(tmp_path: Path) -> None:
    source = tmp_path / "cyber oracle"
    source.mkdir()
    (source / "a.md").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("b", encoding="utf-8")
    (source / "c.pdf").write_text("c", encoding="utf-8")
    (source / "d.docx").write_text("d", encoding="utf-8")
    (source / "skip.png").write_text("x", encoding="utf-8")

    files = iter_supported_files(source)
    names = [path.name for path in files]

    assert names == ["a.md", "b.txt", "c.pdf", "d.docx"]


def test_upsert_env_key_overwrites_existing_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=old\nVECTOR_STORE_ID=vs_old\n", encoding="utf-8")

    upsert_env_key(env_file, "VECTOR_STORE_ID", "vs_new")
    content = env_file.read_text(encoding="utf-8")

    assert "VECTOR_STORE_ID=vs_new" in content
    assert "VECTOR_STORE_ID=vs_old" not in content


def test_build_vector_store_dry_run_does_not_call_openai(tmp_path: Path) -> None:
    source = tmp_path / "cyber oracle"
    source.mkdir()
    (source / "doc.md").write_text("sample", encoding="utf-8")

    result = build_vector_store(
        rag_files_dir=source,
        vector_store_name="vs-test",
        env_file=tmp_path / ".env",
        manifest_path=tmp_path / "manifest.json",
        recreate=False,
        dry_run=True,
    )

    assert isinstance(result, BuildVectorStoreResult)
    assert result.dry_run is True
    assert result.file_count == 1
    assert result.uploaded_file_count == 0
    assert result.vector_store_id == "dry-run"


def test_build_vector_store_writes_rag_manifest_and_preserves_input_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    (rag_dir / "folder").mkdir()
    (rag_dir / "folder" / "a.md").write_text("A", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 2,
                "created_at": "2026-01-01T00:00:00+00:00",
                "input_files_dir": "/tmp/input",
                "rag_files_dir": "/tmp/old-rag",
                "input_files": [
                    {
                        "relative_path": "folder/a.md",
                        "filename": "folder/a.md",
                        "file_id": "input_file_1",
                        "uploaded_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "rag_files": [],
            }
        ),
        encoding="utf-8",
    )

    class FakeFiles:
        def create(self, *, file, purpose: str):  # noqa: ANN001
            assert purpose == "assistants"
            assert file[0] == "folder/a.md"
            return SimpleNamespace(id="rag_file_1")

    class FakeVectorStoreFiles:
        def create_and_poll(self, *, vector_store_id: str, file_id: str) -> None:
            assert vector_store_id == "vs_1"
            assert file_id == "rag_file_1"

    class FakeVectorStores:
        def __init__(self) -> None:
            self.files = FakeVectorStoreFiles()

        def create(self, *, name: str):
            assert name == "vs-test"
            return SimpleNamespace(id="vs_1")

        def delete(self, vector_store_id: str) -> None:
            return None

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = FakeFiles()
            self.vector_stores = FakeVectorStores()

    monkeypatch.setattr("openai_integration.openai_vector_store_builder.OpenAI", FakeOpenAI)

    result = build_vector_store(
        rag_files_dir=rag_dir,
        vector_store_name="vs-test",
        env_file=env_file,
        manifest_path=manifest_path,
        recreate=False,
        dry_run=False,
    )

    assert result.vector_store_id == "vs_1"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["input_files"][0]["file_id"] == "input_file_1"
    assert payload["rag_files"][0]["file_id"] == "rag_file_1"
