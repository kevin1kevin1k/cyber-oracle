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
            self.responses = SimpleNamespace()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(env_file=env_file)

    with pytest.raises(ValueError, match="Run uploader first"):
        client.load_uploaded_files_manifest(tmp_path / "missing.json")


def test_load_manifest_requires_rag_files_mapping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = SimpleNamespace()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(env_file=env_file)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 2,
                "input_files": [
                    {"relative_path": "a.md", "file_id": "input_1"},
                ],
                "rag_files": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Run vector store builder first"):
        client.load_uploaded_files_manifest(manifest_path)


def test_two_stage_response_uses_file_search_tool_and_maps_top_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = {
        "version": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "input_files_dir": "/tmp/input",
        "rag_files_dir": "/tmp/rag",
        "input_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "input_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "relative_path": "folder/b.md",
                "filename": "folder/b.md",
                "file_id": "input_file_2",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
        ],
        "rag_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "rag_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "relative_path": "folder/b.md",
                "filename": "folder/b.md",
                "file_id": "rag_file_2",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            },
        ],
    }
    manifest_path = tmp_path / "input_files_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                output = [
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "rag_file_1",
                                "filename": "folder/a.md",
                                "score": 0.91,
                            },
                            {
                                "file_id": "rag_file_missing",
                                "filename": "folder/missing.md",
                                "score": 0.88,
                            },
                            {
                                "file_id": "rag_file_2",
                                "filename": "folder/b.md",
                                "score": 0.84,
                            },
                        ],
                    }
                ]
                return SimpleNamespace(id="resp_1", output=output, output_text="stage_1")
            return SimpleNamespace(id="resp_2", output=[], output_text="final answer")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = FakeResponses()

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

    assert result.response_text == "final answer"
    assert result.first_response_id == "resp_1"
    assert result.second_response_id == "resp_2"
    assert len(result.input_files) == 2
    assert len(result.top_matches) == 3
    assert len(result.unmatched_top_matches) == 1
    assert result.unmatched_top_matches[0].filename == "folder/missing.md"
    assert result.debug_steps == []

    fake_client = client._client
    assert len(fake_client.responses.calls) == 2

    first_request = fake_client.responses.calls[0]
    assert first_request["tools"][0]["type"] == "file_search"
    assert first_request["tools"][0]["vector_store_ids"] == ["vs_abc"]
    assert first_request["tools"][0]["max_num_results"] == 3

    second_request = fake_client.responses.calls[1]
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert second_file_ids == ["input_file_1", "input_file_2"]


def test_first_stage_falls_back_to_user_role_when_system_role_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = {
        "version": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "input_files_dir": "/tmp/input",
        "rag_files_dir": "/tmp/rag",
        "input_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "input_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "rag_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "rag_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("system-role input_file unsupported")
            if len(self.calls) == 2:
                output = [
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "rag_file_1",
                                "filename": "folder/a.md",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(id="resp_1", output=output, output_text="stage1")
            return SimpleNamespace(id="resp_2", output=[], output_text="final")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    result = client.run_two_stage_response(
        question="Q",
        manifest_path=manifest_path,
        top_k=3,
    )

    assert result.response_text == "final"
    assert result.first_stage_used_system_role is False
    assert result.debug_steps == []
    first_call = client._client.responses.calls[0]
    second_call = client._client.responses.calls[1]
    assert first_call["input"][0]["role"] == "system"
    assert second_call["input"][0]["role"] == "user"


def test_debug_mode_records_step_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = {
        "version": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "input_files_dir": "/tmp/input",
        "rag_files_dir": "/tmp/rag",
        "input_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "input_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "rag_files": [
            {
                "relative_path": "folder/a.md",
                "filename": "folder/a.md",
                "file_id": "rag_file_1",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003
            role = kwargs["input"][0]["role"]
            if role in {"system", "user"} and kwargs.get("tools"):
                output = [
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "rag_file_1",
                                "filename": "folder/a.md",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(id="resp_1", output=output, output_text="stage1")
            return SimpleNamespace(id="resp_2", output=[], output_text="final")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    result = client.run_two_stage_response(
        question="Q",
        manifest_path=manifest_path,
        top_k=3,
        debug=True,
    )

    assert any(line.startswith("1.load_manifest: start") for line in result.debug_steps)
    assert any(line.startswith("1.load_manifest: done (") for line in result.debug_steps)
    assert any(line.startswith("5.second_stage_generate: done (") for line in result.debug_steps)
