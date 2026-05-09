import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openai_integration.openai_file_search_lib import (
    AskStructuredOutput,
    OneStageSearchResult,
    OpenAIFileSearchClient,
    TwoStageSearchResult,
)


def _formatted_answer(seed: str) -> str:
    return "\n\n".join(
        [
            f"1️⃣ 整體結論\n{seed}：結論",
            (
                "2️⃣ 第一層｜核心本質\n"
                f"{seed}：核心本質\n\n"
                "3️⃣ 第二層｜實際作用\n"
                f"{seed}：實際作用\n\n"
                "4️⃣ 第三層｜關鍵行動\n"
                f"{seed}：關鍵行動\n\n"
                "5️⃣ 第四層｜風險與代價\n"
                f"{seed}：風險與代價"
            ),
            f"🌙 籤詩\n{seed}：神諭籤詩",
            f"✨ 行動定錨\n{seed}：定錨語",
            f"🔚 終局收斂\n{seed}：終局收斂",
        ]
    )


def _structured_output_text(answer_seed: str, followups: list[str] | None = None) -> str:
    payload = {
        "conclusion": f"{answer_seed}：結論",
        "layered_analysis": (
            "2️⃣ 第一層｜核心本質\n"
            f"{answer_seed}：核心本質\n\n"
            "3️⃣ 第二層｜實際作用\n"
            f"{answer_seed}：實際作用\n\n"
            "4️⃣ 第三層｜關鍵行動\n"
            f"{answer_seed}：關鍵行動\n\n"
            "5️⃣ 第四層｜風險與代價\n"
            f"{answer_seed}：風險與代價"
        ),
        "oracle_poem": f"{answer_seed}：神諭籤詩",
        "poem_interpretation": f"{answer_seed}：終局收斂",
        "anchoring_phrase": f"{answer_seed}：定錨語",
        "followup_options": followups or [],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_format_structured_answer_renders_new_display_structure() -> None:
    rendered = OpenAIFileSearchClient._format_structured_answer(
        AskStructuredOutput(
            conclusion="直接回答",
            layered_analysis=(
                "2️⃣ 第一層｜核心本質\n核心拆解\n\n"
                "3️⃣ 第二層｜實際作用\n實際作用\n\n"
                "4️⃣ 第三層｜關鍵行動\n關鍵行動\n\n"
                "5️⃣ 第四層｜風險與代價\n風險與代價"
            ),
            oracle_poem="一首籤詩",
            poem_interpretation="最後收斂",
            anchoring_phrase="記住這句話",
            followup_options=["延伸 A"],
        )
    )

    assert rendered == (
        "1️⃣ 整體結論\n直接回答\n\n"
        "2️⃣ 第一層｜核心本質\n核心拆解\n\n"
        "3️⃣ 第二層｜實際作用\n實際作用\n\n"
        "4️⃣ 第三層｜關鍵行動\n關鍵行動\n\n"
        "5️⃣ 第四層｜風險與代價\n風險與代價\n\n"
        "🌙 籤詩\n一首籤詩\n\n"
        "✨ 行動定錨\n記住這句話\n\n"
        "🔚 終局收斂\n最後收斂"
    )


def test_require_non_empty_section_rejects_whitespace_only() -> None:
    with pytest.raises(RuntimeError, match="conclusion"):
        OpenAIFileSearchClient._require_non_empty_section("   ", field_name="conclusion")


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


def test_init_reads_process_env_before_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "env-key"
            self.responses = SimpleNamespace()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("VECTOR_STORE_ID", "vs_env")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=dotenv-key\nVECTOR_STORE_ID=vs_dotenv\n",
        encoding="utf-8",
    )

    client = OpenAIFileSearchClient(env_file=env_file)

    assert client._vector_store_id == "vs_env"


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


def test_one_stage_response_falls_back_when_manifest_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            return SimpleNamespace(
                id="resp_1",
                output=[
                    {
                        "type": "file_search_call",
                        "results": [
                            {
                                "file_id": "vs_file_1",
                                "filename": "doc-a.md",
                                "score": 0.88,
                            }
                        ],
                    }
                ],
                output_text=_structured_output_text("fallback answer", ["延伸 A"]),
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "key"
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(model="gpt-5.2-2025-12-11", env_file=env_file)

    result = client.run_one_stage_response(
        question="問題",
        manifest_path=tmp_path / "missing.json",
        top_k=3,
        system_prompt="你是文件助手",
        debug=True,
    )

    assert result.response_text == _formatted_answer("fallback answer")
    assert result.followup_options == ["延伸 A"]
    assert result.input_files == []
    assert len(result.top_matches) == 1
    fake_client = client._client
    request = fake_client.responses.calls[0]
    assert request["tools"][0]["vector_store_ids"] == ["vs_abc"]
    user_content = request["input"][1]["content"]
    assert user_content == [{"type": "input_text", "text": "問題"}]
    assert any("optional_runtime_fallback" in line for line in result.debug_steps)


def test_one_stage_free_response_uses_plain_text_answer_and_followup_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="resp_free_1",
                    output=[
                        {
                            "type": "file_search_call",
                            "results": [
                                {
                                    "file_id": "vs_file_1",
                                    "filename": "doc-a.md",
                                    "score": 0.88,
                                }
                            ],
                        }
                    ],
                    output_text="這是一段自由回覆答案",
                )
            return SimpleNamespace(
                id="resp_free_followups",
                output=[],
                output_text=json.dumps(
                    {"followup_options": ["延伸 A", "延伸 B"]},
                    ensure_ascii=False,
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

    result = client.run_one_stage_free_response(
        question="問題",
        manifest_path=tmp_path / "missing.json",
        system_prompt="free prompt",
        followup_system_prompt="followup prompt",
        top_k=3,
        debug=True,
    )

    assert result.response_text == "這是一段自由回覆答案"
    assert result.followup_options == ["延伸 A", "延伸 B"]
    first_request = client._client.responses.calls[0]
    second_request = client._client.responses.calls[1]
    assert "text" not in first_request
    assert second_request["text"]["format"]["type"] == "json_schema"
    assert second_request["instructions"] == "followup prompt"


def test_quality_first_structured_response_uses_digest_then_writer_without_attached_files(
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
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="resp_retrieval",
                    output=[
                        {
                            "type": "file_search_call",
                            "results": [
                                {
                                    "file_id": "rag_file_1",
                                    "filename": "folder/a.md",
                                    "score": 0.91,
                                },
                                {
                                    "file_id": "rag_file_2",
                                    "filename": "folder/b.md",
                                    "score": 0.84,
                                },
                            ],
                        }
                    ],
                    output_text="retrieval",
                )
            if len(self.calls) == 2:
                return SimpleNamespace(
                    id="resp_digest",
                    output=[],
                    output_text=json.dumps(
                        {
                            "answer_direction": "主判斷",
                            "evidence_points": ["證據一", "證據二"],
                            "caveats": ["限制一"],
                            "source_filenames": ["folder/a.md", "folder/b.md"],
                        },
                        ensure_ascii=False,
                    ),
                )
            if len(self.calls) == 3:
                return SimpleNamespace(
                    id="resp_writer",
                    output=[],
                    output_text=json.dumps(
                        {
                            "conclusion": "結論",
                            "layered_analysis": (
                                "2️⃣ 第一層｜核心本質\n核心\n\n"
                                "3️⃣ 第二層｜實際作用\n作用\n\n"
                                "4️⃣ 第三層｜關鍵行動\n行動\n\n"
                                "5️⃣ 第四層｜風險與代價\n風險"
                            ),
                            "oracle_poem": "籤詩",
                            "poem_interpretation": "收斂",
                            "anchoring_phrase": "定錨",
                        },
                        ensure_ascii=False,
                    ),
                )
            return SimpleNamespace(
                id="resp_followup",
                output=[],
                output_text=json.dumps(
                    {"followup_options": ["延伸 A", "延伸 B"]},
                    ensure_ascii=False,
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

    result = client.run_quality_first_structured_response(
        question="問題",
        manifest_path=manifest_path,
        writer_system_prompt="writer prompt",
        followup_system_prompt="followup prompt",
        enable_compression=False,
        top_k=5,
        debug=True,
    )

    assert result.response_text == (
        "1️⃣ 整體結論\n結論\n\n"
        "2️⃣ 第一層｜核心本質\n核心\n\n"
        "3️⃣ 第二層｜實際作用\n作用\n\n"
        "4️⃣ 第三層｜關鍵行動\n行動\n\n"
        "5️⃣ 第四層｜風險與代價\n風險\n\n"
        "🌙 籤詩\n籤詩\n\n"
        "✨ 行動定錨\n定錨\n\n"
        "🔚 終局收斂\n收斂"
    )
    assert result.followup_options == ["延伸 A", "延伸 B"]
    assert len(result.top_matches) == 2

    retrieval_request, digest_request, writer_request, followup_request = (
        client._client.responses.calls
    )
    assert retrieval_request["tools"][0]["type"] == "file_search"
    retrieval_user_content = retrieval_request["input"][1]["content"]
    assert retrieval_user_content == [{"type": "input_text", "text": "問題"}]

    digest_file_ids = [
        item["file_id"]
        for item in digest_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert digest_file_ids == ["rag_file_1", "rag_file_2"]
    assert all(file_id != "input_explainer" for file_id in digest_file_ids)
    assert digest_request["text"]["format"]["name"] == "evidence_brief"

    assert "tools" not in writer_request
    assert all(item["type"] != "input_file" for item in writer_request["input"][0]["content"])
    assert writer_request["text"]["format"]["name"] == "ask_structured_sections"
    assert any(
        line.startswith("4.evidence_digest: request_payload=") for line in result.debug_steps
    )
    assert any(
        line.startswith("5.structured_writer: request_payload=") for line in result.debug_steps
    )
    assert followup_request["text"]["format"]["name"] == "ask_followup_output"


def test_quality_first_structured_response_falls_back_to_legacy_two_stage_when_digest_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="resp_retrieval",
                    output=[
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
                    ],
                    output_text="retrieval",
                )
            return SimpleNamespace(
                id="resp_digest",
                output=[],
                output_text="not-json",
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(env_file=env_file)

    called: dict[str, object] = {}

    def fake_legacy(**kwargs):  # noqa: ANN003
        called["kwargs"] = kwargs
        return OneStageSearchResult(
            response_text="legacy answer",
            followup_options=["legacy followup"],
            response_id="legacy_resp",
            input_files=[],
            top_matches=[],
            debug_steps=["legacy"],
        )

    monkeypatch.setattr(client, "run_two_stage_response", fake_legacy)

    result = client.run_quality_first_structured_response(
        question="問題",
        manifest_path=tmp_path / "missing.json",
        writer_system_prompt="writer prompt",
        followup_system_prompt="followup prompt",
        enable_compression=False,
        top_k=5,
        debug=True,
    )

    assert result.response_text == "legacy answer"
    assert result.followup_options == ["legacy followup"]
    assert called["kwargs"]["question"] == "問題"


def test_quality_first_free_response_falls_back_to_legacy_two_stage_free_when_writer_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="resp_retrieval",
                    output=[
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
                    ],
                    output_text="retrieval",
                )
            if len(self.calls) == 2:
                return SimpleNamespace(
                    id="resp_digest",
                    output=[],
                    output_text=json.dumps(
                        {
                            "answer_direction": "主判斷",
                            "evidence_points": ["證據一"],
                            "caveats": [],
                            "source_filenames": ["folder/a.md"],
                        },
                        ensure_ascii=False,
                    ),
                )
            return SimpleNamespace(
                id="resp_writer",
                output=[],
                output_text="   ",
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")
    client = OpenAIFileSearchClient(env_file=env_file)

    called: dict[str, object] = {}

    def fake_legacy(**kwargs):  # noqa: ANN003
        called["kwargs"] = kwargs
        return TwoStageSearchResult(
            response_text="legacy free answer",
            followup_options=["legacy free followup"],
            first_response_id="legacy_first",
            second_response_id="legacy_second",
            input_files=[],
            top_matches=[],
            unmatched_top_matches=[],
            debug_steps=["legacy free"],
        )

    monkeypatch.setattr(client, "run_two_stage_free_response", fake_legacy)

    result = client.run_quality_first_free_response(
        question="問題",
        manifest_path=tmp_path / "missing.json",
        writer_system_prompt="free writer",
        followup_system_prompt="followup prompt",
        top_k=5,
        debug=True,
    )

    assert result.response_text == "legacy free answer"
    assert result.followup_options == ["legacy free followup"]
    assert called["kwargs"]["question"] == "問題"


def test_two_stage_response_falls_back_to_vector_file_ids_when_manifest_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def create(self, **kwargs):  # noqa: ANN003
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="resp_1",
                    output=[
                        {
                            "type": "file_search_call",
                            "results": [
                                {
                                    "file_id": "vs_file_1",
                                    "filename": "doc-a.md",
                                    "score": 0.91,
                                },
                                {
                                    "file_id": "vs_file_2",
                                    "filename": "doc-b.md",
                                    "score": 0.84,
                                },
                            ],
                        }
                    ],
                    output_text="stage_1",
                )
            return SimpleNamespace(
                id="resp_2",
                output=[],
                output_text=_structured_output_text("two stage fallback", ["延伸 B"]),
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
        manifest_path=tmp_path / "missing.json",
        top_k=3,
        system_prompt="你是文件助手",
        debug=True,
    )

    assert result.response_text == _formatted_answer("two stage fallback")
    assert result.followup_options == ["延伸 B"]
    assert result.input_files == []
    assert len(result.top_matches) == 2
    assert result.unmatched_top_matches == []
    fake_client = client._client
    second_request = fake_client.responses.calls[1]
    second_file_ids = [
        item["file_id"]
        for item in second_request["input"][0]["content"]
        if item["type"] == "input_file"
    ]
    assert second_file_ids == ["vs_file_1", "vs_file_2"]
    assert any("direct_vector_file_ids" in line for line in result.debug_steps)


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

    assert result.response_text == _formatted_answer("final answer")
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

    assert result.response_text == _formatted_answer("final")
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

    assert result.response_text == _formatted_answer("one stage answer")
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
        "conclusion",
        "layered_analysis",
        "oracle_poem",
        "poem_interpretation",
        "anchoring_phrase",
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

    assert result.response_text == _formatted_answer("final")
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

    assert result.response_text == _formatted_answer("final")
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


def test_normalize_followup_options_filters_questionnaire_style_and_partial_options() -> None:
    values = [
        "你的目標是減脂、增肌、體能、睡眠或抗壓？（選一個優先）",
        "我優先：減脂",
        "提供你的身高/體重/年齡/性別與一日作息，我幫你找最小改動槓桿",
        "如果我想把主導權從家長拉回到我們兩個，最小衝突的做法是什麼？",
        "如何設一個「溝通框架」讓討論不再繞圈（每次談判的固定順序與句型）？",
    ]

    normalized = OpenAIFileSearchClient._normalize_followup_options(values)

    assert normalized == [
        "如果我想把主導權從家長拉回到我們兩個，最小衝突的做法是什麼？",
        "如何設一個「溝通框架」讓討論不再繞圈（每次談判的固定順序與句型）？",
    ]


def test_normalize_followup_options_dedupes_and_caps_valid_questions() -> None:
    values = [
        "如果其實是我在扛，但我已經快扛不住了，我該怎麼重新分工？",
        "如果其實是我在扛，但我已經快扛不住了，我該怎麼重新分工？",
        "用「決策權／金流權／溝通權」三條線，幫我判斷目前主導權各落在誰身上",
        "如果我想把主導權從家長拉回到我們兩個，最小衝突的做法是什麼？",
        "如何設一個「溝通框架」讓討論不再繞圈（每次談判的固定順序與句型）？",
    ]

    normalized = OpenAIFileSearchClient._normalize_followup_options(values)

    assert normalized == [
        "如果其實是我在扛，但我已經快扛不住了，我該怎麼重新分工？",
        "用「決策權／金流權／溝通權」三條線，幫我判斷目前主導權各落在誰身上",
        "如果我想把主導權從家長拉回到我們兩個，最小衝突的做法是什麼？",
    ]


def test_one_stage_response_applies_compression_and_preserves_followups(
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
                                "filename": "a.md",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(
                    id="resp_stage_1",
                    output=output,
                    output_text=_structured_output_text("原始回答", ["延伸 A", "延伸 B"]),
                )
            return SimpleNamespace(
                id="resp_compression",
                output=[],
                output_text=_structured_output_text(
                    "壓縮後回答",
                    ["被改寫的延伸題", "第二個被改寫延伸題"],
                ),
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    result = client.run_one_stage_response(
        question="問題",
        manifest_path=manifest_path,
        top_k=3,
        enable_compression=True,
        compression_system_prompt="compression prompt",
        debug=True,
    )

    assert result.response_text == _formatted_answer("壓縮後回答")
    assert result.followup_options == ["延伸 A", "延伸 B"]
    compression_request = client._client.responses.calls[1]
    assert compression_request["instructions"] == "compression prompt"
    assert compression_request["input"][0]["content"][0]["text"] == "原始問題：問題"


def test_one_stage_response_falls_back_when_compression_output_is_invalid(
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
                                "filename": "a.md",
                                "score": 0.9,
                            }
                        ],
                    }
                ]
                return SimpleNamespace(
                    id="resp_stage_1",
                    output=output,
                    output_text=_structured_output_text("原始回答", ["延伸 A"]),
                )
            return SimpleNamespace(
                id="resp_compression",
                output=[],
                output_text='{"conclusion": ""}',
            )

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai_integration.openai_file_search_lib.OpenAI", FakeOpenAI)

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=key\nVECTOR_STORE_ID=vs_abc\n", encoding="utf-8")

    client = OpenAIFileSearchClient(env_file=env_file)
    result = client.run_one_stage_response(
        question="問題",
        manifest_path=manifest_path,
        top_k=3,
        enable_compression=True,
        compression_system_prompt="compression prompt",
        debug=True,
    )

    assert result.response_text == _formatted_answer("原始回答")
    assert result.followup_options == ["延伸 A"]
    assert any("compression_failed_fallback" in line for line in result.debug_steps)
