from types import SimpleNamespace

from app import main as main_module


def test_generate_answer_uses_one_stage_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, model: str) -> None:
            called["init_model"] = model

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "one_stage"
            called["kwargs"] = kwargs
            return SimpleNamespace(response_text="one stage answer", top_matches=[])

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

    answer, source = main_module._generate_answer_from_openai_file_search("問題")

    assert answer == "one stage answer"
    assert source == "openai"
    assert called["pipeline"] == "one_stage"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 3
    assert kwargs["model"] == "gpt-5.2-2025-12-11"


def test_generate_answer_uses_two_stage_pipeline(monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, model: str) -> None:
            called["init_model"] = model

        def run_one_stage_response(self, **kwargs):  # noqa: ANN003
            raise AssertionError("run_one_stage_response should not be called in two_stage mode")

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            called["pipeline"] = "two_stage"
            called["kwargs"] = kwargs
            return SimpleNamespace(response_text="two stage answer", top_matches=[object()])

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

    answer, source = main_module._generate_answer_from_openai_file_search("問題")

    assert answer == "two stage answer"
    assert source == "rag"
    assert called["pipeline"] == "two_stage"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["top_k"] == 3
    assert kwargs["model"] == "gpt-5.2-2025-12-11"
    assert kwargs["system_prompt"] == "sys"
