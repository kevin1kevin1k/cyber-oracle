from pathlib import Path
from types import SimpleNamespace

from openai_integration import openai_file_search_main


def test_main_parses_manifest_path_and_debug_flag(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    called: dict[str, object] = {}
    manifest_path = tmp_path / "input_files_manifest.json"

    class FakeClient:
        def __init__(self, model: str) -> None:
            called["init_model"] = model

        def run_two_stage_response(self, **kwargs):  # noqa: ANN003
            called["kwargs"] = kwargs
            return SimpleNamespace(
                response_text="final answer",
                first_response_id="resp_1",
                second_response_id="resp_2",
                input_files=[SimpleNamespace(file_id="f1")],
                top_matches=[],
                unmatched_top_matches=[],
                first_stage_used_system_role=True,
                debug_steps=[
                    "1.load_manifest: start",
                    "1.load_manifest: done (1.23 ms)",
                ],
            )

    monkeypatch.setattr(openai_file_search_main, "OpenAIFileSearchClient", FakeClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "openai_file_search_main",
            "--question",
            "問題",
            "--manifest-path",
            str(manifest_path),
            "--top-k",
            "3",
            "--debug",
        ],
    )

    openai_file_search_main.main()

    out = capsys.readouterr().out
    assert "final answer" in out
    assert "first_stage_used_system_role=True" in out
    assert "step_logs:" in out
    assert "1.load_manifest: done" in out

    assert called["init_model"] == "gpt-4.1-mini"
    kwargs = called["kwargs"]
    assert kwargs["question"] == "問題"
    assert kwargs["manifest_path"] == manifest_path.resolve()
    assert kwargs["top_k"] == 3
    assert kwargs["debug"] is True
