from types import SimpleNamespace

from app import main as main_module


def test_generate_answer_uses_quality_first_structured_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str | None = None,
            model: str,
            vector_store_id: str | None = None,
        ) -> None:
            called["init_model"] = model
            called["init_api_key"] = api_key
            called["init_vector_store_id"] = vector_store_id

        def run_quality_first_structured_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "quality_first_structured"
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="quality-first structured answer",
                top_matches=[object()],
                followup_options=["延伸 Q1", "延伸 Q2"],
            )

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError(
                "run_one_stage_response should not be called in quality_first mode"
            )

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError(
                "run_two_stage_response should not be called in quality_first mode"
            )

    monkeypatch.setattr(main_module, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(main_module.settings, "openai_ask_pipeline", "quality_first")
    monkeypatch.setattr(
        main_module.settings,
        "openai_manifest_path",
        "openai_integration/input_files_manifest.json",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_model", "gpt-5.2-2025-12-11")
    monkeypatch.setattr(main_module.settings, "openai_ask_top_k", 5)
    monkeypatch.setattr(
        main_module.settings,
        "openai_ask_system_prompt",
        "structured-writer-prompt",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_enable_compression", True, raising=False)
    monkeypatch.setattr(
        main_module.settings,
        "openai_ask_compression_system_prompt",
        "compression-sys",
        raising=False,
    )
    monkeypatch.setattr(main_module.settings, "openai_api_key", "render-key")
    monkeypatch.setattr(main_module.settings, "vector_store_id", "vs_render")

    answer, source, followups = main_module._generate_answer_from_openai_file_search("問題")

    assert answer == "quality-first structured answer"
    assert source == "rag"
    assert followups == ["延伸 Q1", "延伸 Q2"]
    assert called["pipeline"] == "quality_first_structured"
    assert called["init_api_key"] == "render-key"
    assert called["init_vector_store_id"] == "vs_render"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 5
    assert kwargs["model"] == "gpt-5.2-2025-12-11"
    assert kwargs["writer_system_prompt"] == "structured-writer-prompt"
    assert kwargs["enable_compression"] is True
    assert kwargs["compression_system_prompt"] == "compression-sys"


def test_generate_answer_uses_quality_first_free_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str | None = None,
            model: str,
            vector_store_id: str | None = None,
        ) -> None:
            called["init_model"] = model
            called["init_api_key"] = api_key
            called["init_vector_store_id"] = vector_store_id

        def run_quality_first_free_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "quality_first_free"
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="quality-first free answer",
                top_matches=[object()],
                followup_options=["延伸 F1"],
            )

        def run_one_stage_free_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError(
                "run_one_stage_free_response should not be called in quality_first mode"
            )

        def run_two_stage_free_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError(
                "run_two_stage_free_response should not be called in quality_first mode"
            )

    monkeypatch.setattr(main_module, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(main_module.settings, "openai_ask_pipeline", "quality_first")
    monkeypatch.setattr(
        main_module.settings,
        "openai_manifest_path",
        "openai_integration/input_files_manifest.json",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_model", "gpt-5.2-2025-12-11")
    monkeypatch.setattr(main_module.settings, "openai_ask_top_k", 5)
    monkeypatch.setattr(
        main_module.settings,
        "openai_free_ask_system_prompt",
        "free-writer-prompt",
    )
    monkeypatch.setattr(
        main_module.settings,
        "openai_free_followup_system_prompt",
        "followup-prompt",
    )
    monkeypatch.setattr(main_module.settings, "openai_api_key", "render-key")
    monkeypatch.setattr(main_module.settings, "vector_store_id", "vs_render")

    answer, source, followups = main_module._generate_answer_from_openai_file_search(
        "問題",
        reply_mode="free",
    )

    assert answer == "quality-first free answer"
    assert source == "rag"
    assert followups == ["延伸 F1"]
    assert called["pipeline"] == "quality_first_free"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 5
    assert kwargs["model"] == "gpt-5.2-2025-12-11"
    assert kwargs["writer_system_prompt"] == "free-writer-prompt"
    assert kwargs["followup_system_prompt"] == "followup-prompt"


def test_generate_answer_uses_one_stage_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str | None = None,
            model: str,
            vector_store_id: str | None = None,
        ) -> None:
            called["init_model"] = model
            called["init_api_key"] = api_key
            called["init_vector_store_id"] = vector_store_id

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "one_stage"
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="one stage answer",
                top_matches=[],
                followup_options=["延伸 A", "延伸 B"],
            )

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError("run_two_stage_response should not be called in one_stage mode")

    monkeypatch.setattr(main_module, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(main_module.settings, "openai_ask_pipeline", "one_stage")
    monkeypatch.setattr(
        main_module.settings,
        "openai_manifest_path",
        "openai_integration/input_files_manifest.json",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_model", "gpt-5.2-2025-12-11")
    monkeypatch.setattr(main_module.settings, "openai_ask_top_k", 3)
    monkeypatch.setattr(main_module.settings, "openai_ask_system_prompt", "sys")
    monkeypatch.setattr(main_module.settings, "openai_ask_enable_compression", True, raising=False)
    monkeypatch.setattr(
        main_module.settings,
        "openai_ask_compression_system_prompt",
        "compression-sys",
        raising=False,
    )
    monkeypatch.setattr(main_module.settings, "openai_api_key", "render-key")
    monkeypatch.setattr(main_module.settings, "vector_store_id", "vs_render")

    answer, source, followups = main_module._generate_answer_from_openai_file_search("問題")

    assert answer == "one stage answer"
    assert source == "openai"
    assert followups == ["延伸 A", "延伸 B"]
    assert called["pipeline"] == "one_stage"
    assert called["init_api_key"] == "render-key"
    assert called["init_vector_store_id"] == "vs_render"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 3
    assert kwargs["model"] == "gpt-5.2-2025-12-11"
    assert kwargs["system_prompt"] == "sys"
    assert kwargs["enable_compression"] is True
    assert kwargs["compression_system_prompt"] == "compression-sys"


def test_generate_answer_uses_free_output_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str | None = None,
            model: str,
            vector_store_id: str | None = None,
        ) -> None:
            called["init_model"] = model
            called["init_api_key"] = api_key
            called["init_vector_store_id"] = vector_store_id

        def run_one_stage_free_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "one_stage_free"
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="自由回覆答案",
                top_matches=[],
                followup_options=["延伸 F1", "延伸 F2"],
            )

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError("run_one_stage_response should not be called in free mode")

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError("run_two_stage_response should not be called in free mode")

    monkeypatch.setattr(main_module, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(main_module.settings, "openai_ask_pipeline", "one_stage")
    monkeypatch.setattr(
        main_module.settings,
        "openai_manifest_path",
        "openai_integration/input_files_manifest.json",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_model", "gpt-5.2-2025-12-11")
    monkeypatch.setattr(main_module.settings, "openai_ask_top_k", 3)
    monkeypatch.setattr(main_module.settings, "openai_api_key", "render-key")
    monkeypatch.setattr(main_module.settings, "vector_store_id", "vs_render")

    answer, source, followups = main_module._generate_answer_from_openai_file_search(
        "問題",
        reply_mode="free",
    )

    assert answer == "自由回覆答案"
    assert source == "openai"
    assert followups == ["延伸 F1", "延伸 F2"]
    assert called["pipeline"] == "one_stage_free"


def test_generate_answer_uses_two_stage_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(
            self,
            *,
            api_key: str | None = None,
            model: str,
            vector_store_id: str | None = None,
        ) -> None:
            called["init_model"] = model
            called["init_api_key"] = api_key
            called["init_vector_store_id"] = vector_store_id

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError("run_one_stage_response should not be called in two_stage mode")

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "two_stage"
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="two stage answer",
                top_matches=[object()],
                followup_options=["延伸 X"],
            )

    monkeypatch.setattr(main_module, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(main_module.settings, "openai_ask_pipeline", "two_stage")
    monkeypatch.setattr(
        main_module.settings,
        "openai_manifest_path",
        "openai_integration/input_files_manifest.json",
    )
    monkeypatch.setattr(main_module.settings, "openai_ask_model", "gpt-5.2-2025-12-11")
    monkeypatch.setattr(main_module.settings, "openai_ask_top_k", 3)
    monkeypatch.setattr(main_module.settings, "openai_ask_system_prompt", "sys")
    monkeypatch.setattr(main_module.settings, "openai_ask_enable_compression", True, raising=False)
    monkeypatch.setattr(
        main_module.settings,
        "openai_ask_compression_system_prompt",
        "compression-sys",
        raising=False,
    )
    monkeypatch.setattr(main_module.settings, "openai_api_key", "render-key")
    monkeypatch.setattr(main_module.settings, "vector_store_id", "vs_render")

    answer, source, followups = main_module._generate_answer_from_openai_file_search("問題")

    assert answer == "two stage answer"
    assert source == "rag"
    assert followups == ["延伸 X"]
    assert called["pipeline"] == "two_stage"
    assert called["init_api_key"] == "render-key"
    assert called["init_vector_store_id"] == "vs_render"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 3
    assert kwargs["model"] == "gpt-5.2-2025-12-11"
    assert kwargs["system_prompt"] == "sys"
    assert kwargs["enable_compression"] is True
    assert kwargs["compression_system_prompt"] == "compression-sys"
