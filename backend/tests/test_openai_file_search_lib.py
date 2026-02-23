import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_integration.openai_file_search_lib import OpenAIFileSearchClient


def test_init_requires_openai_api_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VECTOR_STORE_ID=vs_123\n", encoding="utf-8")

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIFileSearchClient(env_file=env_file)


def test_init_requires_vector_store_id(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\n", encoding="utf-8")

    with pytest.raises(ValueError, match="VECTOR_STORE_ID"):
        OpenAIFileSearchClient(env_file=env_file)


def test_load_manifest_requires_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.files = SimpleNamespace()
            self.responses = SimpleNamespace()
            self.vector_stores = SimpleNamespace()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(env_file=env_file)

    with pytest.raises(ValueError, match="Run uploader first"):
        client.load_uploaded_files_manifest(tmp_path / "missing.json")


def test_two_stage_response_reads_manifest_and_skips_unmatched_top_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = {
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "input_files_dir": "/tmp/input",
        "files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "relative_path": "folder/b.md",
                "filename": "folder/b.md",
                "file_id": "file_2",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
        ],
    }
    manifest_path = tmp_path / "input_files_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.counter = 0

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            self.counter += 1
            return SimpleNamespace(id=f"resp_{self.counter}", output_text=f"text_{self.counter}")

    class FakeVectorStores:
        def search(self, vector_store_id: str, **kwargs):  # noqa: ANN003
            assert vector_store_id == "vs_abc"
            assert kwargs["query"] == "問題"
            assert kwargs["max_num_results"] == 3
            return [
                SimpleNamespace(file_id="vs_file_1", filename="folder/a.md", score=0.91),
                SimpleNamespace(file_id="vs_file_2", filename="folder/missing.md", score=0.88),
                SimpleNamespace(file_id="vs_file_3", filename="folder/b.md", score=0.84),
            ]

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = FakeResponses()
            self.vector_stores = FakeVectorStores()
            self.files = SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(  # noqa: ARG005
                    AssertionError("files.create should not be called in main flow")
                )
            )

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(model="gpt-4.1-mini", env_file=env_file)
    result = client.run_two_stage_response(
        question="問題",
        manifest_path=manifest_path,
        top_k=3,
        system_prompt="你是文件助手",
    )

    assert result.response_text == "text_2"
    assert result.first_response_id == "resp_1"
    assert result.second_response_id == "resp_2"
    assert len(result.uploaded_files) == 2
    assert len(result.unmatched_top_matches) == 1
    assert result.unmatched_top_matches[0].filename == "folder/missing.md"

    fake_client = client._client
    assert len(fake_client.responses.calls) == 2
    first_request = fake_client.responses.calls[0]
    second_request = fake_client.responses.calls[1]

    first_file_ids = [
        item["file_id"]
        for item in first_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert first_file_ids == ["file_1", "file_2"]
    assert second_file_ids == ["file_1", "file_2"]
