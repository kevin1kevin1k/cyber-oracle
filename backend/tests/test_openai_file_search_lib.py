import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_integration.openai_file_search_lib import OpenAIFileSearchClient


def _structured_output_text(answer: str, followups: list[str] | None = None) -> str:
    payload = {
        "answer": answer,
        "followup_options": followups or [],
    }
    return json.dumps(payload, ensure_ascii=False)


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
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text(
                    "final answer",
                    ["延伸 A", "延伸 B", "延伸 C"],
                ),
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(model="gpt-5.2-2025-12-11", env_file=env_file)
    result = client.run_two_stage_response(
        question="問題",
        manifest_path=manifest_path,
        top_k=3,
        system_prompt="你是文件助手",
    )

    assert result.response_text == "final answer"
    assert result.followup_options == ["延伸 A", "延伸 B", "延伸 C"]
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
    assert second_request["text"]["format"]["type"] == "json_schema"
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert second_file_ids == ["input_file_1", "input_file_2", "rag_file_1", "rag_file_2"]


def test_first_stage_uses_system_prompt_and_user_question_files(
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
            if kwargs.get("tools"):
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
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text("final", ["延伸 1"]),
            )

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
    assert result.followup_options == ["延伸 1"]
    assert result.debug_steps == []
    first_call = client._client.responses.calls[0]
    first_input = first_call["input"]
    assert len(first_input) == 2
    assert first_input[0]["role"] == "system"
    assert first_input[1]["role"] == "user"
    system_types = [item["type"] for item in first_input[0]["content"]]
    user_types = [item["type"] for item in first_input[1]["content"]]
    assert system_types == ["input_text"]
    assert user_types == ["input_text", "input_file"]


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
            if kwargs.get("tools"):
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
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text("final", ["延伸 1"]),
            )

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
    assert any(
        line.startswith("2.first_stage_file_search: request_payload=")
        for line in result.debug_steps
    )
    assert any(
        line.startswith("3.extract_top_matches: raw_response=") for line in result.debug_steps
    )
    assert any(
        line.startswith("5.second_stage_generate: request_payload=")
        for line in result.debug_steps
    )
    assert any(line.startswith("5.second_stage_generate: done (") for line in result.debug_steps)


def test_one_stage_response_uses_single_file_search_request(
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
            output = [
                {
                    "type": "file_search_call",
                    "results": [
                        {
                            "file_id": "rag_file_1",
                            "filename": "folder/a.md",
                            "score": 0.91,
                        }
                    ],
                }
            ]
            return SimpleNamespace(
                id="resp_one",
                output=output,
                output_text=_structured_output_text(
                    "one stage answer",
                    ["延伸 A", "延伸 A", "延伸 B", "  ", "延伸 C", "延伸 D"],
                ),
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    result = client.run_one_stage_response(
        question="Q",
        manifest_path=manifest_path,
        top_k=3,
        debug=True,
    )

    assert result.response_text == "one stage answer"
    assert result.followup_options == ["延伸 A", "延伸 B", "延伸 C"]
    assert result.response_id == "resp_one"
    assert len(result.top_matches) == 1
    assert any(
        line.startswith("2.one_stage_generate_with_file_search: start")
        for line in result.debug_steps
    )
    assert any(
        line.startswith("2.one_stage_generate_with_file_search: request_payload=")
        for line in result.debug_steps
    )

    fake_client = client._client
    assert len(fake_client.responses.calls) == 1
    request = fake_client.responses.calls[0]
    assert request["tools"][0]["type"] == "file_search"
    assert request["tools"][0]["vector_store_ids"] == ["vs_abc"]
    assert request["tools"][0]["max_num_results"] == 3
    assert request["text"]["format"]["type"] == "json_schema"
    assert set(request["text"]["format"]["schema"]["required"]) == {
        "answer",
        "followup_options",
    }


def test_map_falls_back_to_vector_file_id_when_input_mapping_missing(
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
                "relative_path": "explainer.pdf",
                "filename": "explainer.pdf",
                "file_id": "input_explainer",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "rag_files": [
            {
                "relative_path": "rag_only.pdf",
                "filename": "rag_only.pdf",
                "file_id": "rag_file_only",
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
                output = [
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "rag_file_only",
                                "filename": "rag_only.pdf",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(id="resp_1", output=output, output_text="stage1")
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text("final"),
            )

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

    assert result.response_text == "final"
    assert len(result.unmatched_top_matches) == 0
    assert result.top_matches[0].matched_input_file_id == "rag_file_only"
    assert not any("fallback_to_vector_file_id" in line for line in result.debug_steps)

    second_request = client._client.responses.calls[1]
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert second_file_ids == ["input_explainer", "rag_file_only"]


def test_map_does_not_fallback_to_non_pdf_vector_file(
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
                "relative_path": "explainer.pdf",
                "filename": "explainer.pdf",
                "file_id": "input_explainer",
                "uploaded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "rag_files": [
            {
                "relative_path": "rag_only.md",
                "filename": "rag_only.md",
                "file_id": "rag_file_md",
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
                output = [
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "rag_file_md",
                                "filename": "rag_only.md",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(id="resp_1", output=output, output_text="stage1")
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text("final"),
            )

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

    assert result.response_text == "final"
    assert len(result.unmatched_top_matches) == 0
    assert not any("skipped_unsupported_extension" in line for line in result.debug_steps)

    second_request = client._client.responses.calls[1]
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert second_file_ids == ["input_explainer", "rag_file_md"]


def test_one_stage_raises_on_invalid_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = {
        "version": 2,
        "input_files": [{"relative_path": "a.md", "file_id": "input_file_1"}],
        "rag_files": [{"relative_path": "a.md", "file_id": "rag_file_1"}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003
            output = [
                {
                    "type": "file_search_call",
                    "results": [
                        {
                            "file_id": "rag_file_1",
                            "filename": "a.md",
                            "score": 0.9,
                        }
                    ],
                }
            ]
            return SimpleNamespace(id="resp_bad", output=output, output_text="not-json")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    with pytest.raises(RuntimeError, match="Structured output parse failed"):
        client.run_one_stage_response(
            question="Q",
            manifest_path=manifest_path,
            top_k=3,
            debug=True,
        )
