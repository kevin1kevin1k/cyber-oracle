from pathlib import Path

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
        source_dir=source,
        vector_store_name="vs-test",
        env_file=tmp_path / ".env",
        recreate=False,
        dry_run=True,
    )

    assert isinstance(result, BuildVectorStoreResult)
    assert result.dry_run is True
    assert result.file_count == 1
    assert result.uploaded_file_count == 0
    assert result.vector_store_id == "dry-run"
