from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import dotenv_values
from openai import OpenAI

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "input_files_manifest.json"
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
FIRST_STAGE_FILE_SEARCH_PROMPT = (
    "You are a retrieval step. Read the user question and the attached input files, "
    "then use file_search tool over the configured vector store to find the top 3 most "
    "relevant documents. Prioritize precision and relevance."
)


def _read_dotenv_value(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None
    values = dotenv_values(env_file)
    value = values.get(key)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalize_relative_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./")


@dataclass
class UploadedFile:
    relative_path: str
    file_id: str


@dataclass
class ManifestFiles:
    input_files: list[UploadedFile]
    rag_files: list[UploadedFile]


@dataclass
class TopMatch:
    vector_file_id: str
    filename: str | None
    score: float | None
    matched_input_file_id: str | None


@dataclass
class TwoStageSearchResult:
    response_text: str
    first_response_id: str
    second_response_id: str
    input_files: list[UploadedFile]
    top_matches: list[TopMatch]
    unmatched_top_matches: list[TopMatch]
    first_stage_used_system_role: bool
    debug_steps: list[str]


class OpenAIFileSearchClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        vector_store_id: str | None = None,
        env_file: Path | None = None,
    ) -> None:
        candidate_env = env_file or DEFAULT_ENV_FILE

        resolved_api_key = api_key or _read_dotenv_value(candidate_env, "OPENAI_API_KEY")
        if not resolved_api_key:
            raise ValueError("OPENAI_API_KEY is required")

        resolved_vector_store_id = vector_store_id or _read_dotenv_value(
            candidate_env, "VECTOR_STORE_ID"
        )
        if not resolved_vector_store_id:
            raise ValueError("VECTOR_STORE_ID is required")

        self._client = OpenAI(api_key=resolved_api_key)
        self._model = model
        self._vector_store_id = resolved_vector_store_id

    def run_two_stage_response(
        self,
        *,
        question: str,
        manifest_path: Path,
        system_prompt: str | None = None,
        top_k: int = 3,
        model: str | None = None,
        debug: bool = False,
    ) -> TwoStageSearchResult:
        debug_steps: list[str] = []

        def run_step(step_name: str, func):  # noqa: ANN001
            if debug:
                debug_steps.append(f"{step_name}: start")
            started = perf_counter()
            result = func()
            duration_ms = (perf_counter() - started) * 1000.0
            if debug:
                debug_steps.append(f"{step_name}: done ({duration_ms:.2f} ms)")
            return result

        manifest = run_step(
            "1.load_manifest",
            lambda: self.load_uploaded_files_manifest(manifest_path),
        )
        input_file_ids = [item.file_id for item in manifest.input_files]

        first_response, used_system_role = run_step(
            "2.first_stage_file_search",
            lambda: self._create_first_stage_with_file_search(
                question=question,
                input_file_ids=input_file_ids,
                top_k=top_k,
                model=model,
            ),
        )
        first_response_id = getattr(first_response, "id", "")
        top_matches = run_step(
            "3.extract_top_matches",
            lambda: self._extract_top_matches_from_response(first_response),
        )

        matched_top_file_ids, unmatched_top_matches = run_step(
            "4.map_vs_to_input_files",
            lambda: self._map_top_matches_to_uploaded_files(
                top_matches=top_matches,
                manifest=manifest,
            ),
        )

        second_file_ids = self._dedupe_preserve_order(input_file_ids + matched_top_file_ids)
        second_response = run_step(
            "5.second_stage_generate",
            lambda: self._create_response_request(
                question=question,
                file_ids=second_file_ids,
                system_prompt=system_prompt,
                model=model,
            ),
        )
        second_response_id = getattr(second_response, "id", "")
        response_text = getattr(second_response, "output_text", "") or ""

        return TwoStageSearchResult(
            response_text=response_text,
            first_response_id=first_response_id,
            second_response_id=second_response_id,
            input_files=manifest.input_files,
            top_matches=top_matches,
            unmatched_top_matches=unmatched_top_matches,
            first_stage_used_system_role=used_system_role,
            debug_steps=debug_steps,
        )

    def load_uploaded_files_manifest(self, manifest_path: Path) -> ManifestFiles:
        if not manifest_path.exists():
            raise ValueError(
                "Input files manifest not found. Run uploader first: "
                "python -m openai_integration.openai_input_files_uploader"
            )

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc

        input_entries = payload.get("input_files")
        if not isinstance(input_entries, list) or not input_entries:
            raise ValueError(
                "Manifest input_files is empty. Run uploader first: "
                "python -m openai_integration.openai_input_files_uploader"
            )
        rag_entries = payload.get("rag_files")
        if not isinstance(rag_entries, list) or not rag_entries:
            raise ValueError(
                "Manifest rag_files is empty. Run vector store builder first: "
                "python -m openai_integration.openai_vector_store_builder"
            )

        input_files = self._parse_manifest_entries(input_entries, "input_files")
        rag_files = self._parse_manifest_entries(rag_entries, "rag_files")
        return ManifestFiles(input_files=input_files, rag_files=rag_files)

    def _parse_manifest_entries(self, entries: Any, field_name: str) -> list[UploadedFile]:
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Manifest must include non-empty {field_name}")

        parsed: list[UploadedFile] = []
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError(f"Manifest {field_name} entry must be object")
            relative_path = item.get("relative_path")
            file_id = item.get("file_id")
            if not isinstance(relative_path, str) or not relative_path.strip():
                raise ValueError(f"Manifest {field_name} entry missing relative_path")
            if not isinstance(file_id, str) or not file_id.strip():
                raise ValueError(f"Manifest {field_name} entry missing file_id")
            parsed.append(
                UploadedFile(
                    relative_path=_normalize_relative_path(relative_path),
                    file_id=file_id.strip(),
                )
            )
        return parsed

    def _create_first_stage_with_file_search(
        self,
        *,
        question: str,
        input_file_ids: list[str],
        top_k: int,
        model: str | None,
    ) -> tuple[Any, bool]:
        top_k = max(1, top_k)
        content_items = [{"type": "input_text", "text": question}]
        for file_id in input_file_ids:
            content_items.append({"type": "input_file", "file_id": file_id})

        base_payload: dict[str, Any] = {
            "model": model or self._model,
            "instructions": FIRST_STAGE_FILE_SEARCH_PROMPT,
            "tools": [
                {
                    "type": "file_search",
                    "vector_store_ids": [self._vector_store_id],
                    "max_num_results": top_k,
                }
            ],
        }

        try:
            response = self._client.responses.create(
                **base_payload,
                input=[{"role": "system", "content": content_items}],
            )
            return response, True
        except Exception:
            response = self._client.responses.create(
                **base_payload,
                input=[{"role": "user", "content": content_items}],
            )
            return response, False

    def _extract_top_matches_from_response(self, response: Any) -> list[TopMatch]:
        max_candidates = 3
        candidates: list[TopMatch] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                file_id = value.get("file_id")
                filename = value.get("filename")
                score = value.get("score")
                if isinstance(file_id, str) and file_id:
                    normalized_score = float(score) if isinstance(score, (int, float)) else None
                    candidates.append(
                        TopMatch(
                            vector_file_id=file_id,
                            filename=filename if isinstance(filename, str) else None,
                            score=normalized_score,
                            matched_input_file_id=None,
                        )
                    )
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            else:
                object_dict = getattr(value, "__dict__", None)
                if isinstance(object_dict, dict):
                    walk(object_dict)

        walk(response)

        deduped: list[TopMatch] = []
        seen: set[tuple[str, str]] = set()
        for match in candidates:
            filename_key = match.filename or ""
            key = (match.vector_file_id, filename_key)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(match)

        deduped.sort(key=lambda item: item.score if item.score is not None else -1.0, reverse=True)
        return deduped[:max_candidates]

    def _create_response_request(
        self,
        *,
        question: str,
        file_ids: list[str],
        system_prompt: str | None,
        model: str | None,
    ) -> Any:
        content_items: list[dict[str, Any]] = [{"type": "input_text", "text": question}]
        for file_id in file_ids:
            content_items.append({"type": "input_file", "file_id": file_id})

        return self._client.responses.create(
            model=model or self._model,
            instructions=system_prompt or "",
            input=[
                {
                    "role": "user",
                    "content": content_items,
                }
            ],
        )

    def _map_top_matches_to_uploaded_files(
        self,
        *,
        top_matches: list[TopMatch],
        manifest: ManifestFiles,
    ) -> tuple[list[str], list[TopMatch]]:
        input_mapping = {
            _normalize_relative_path(item.relative_path): item.file_id
            for item in manifest.input_files
        }
        rag_by_file_id = {item.file_id: item.relative_path for item in manifest.rag_files}
        rag_by_path = {item.relative_path: item.relative_path for item in manifest.rag_files}

        matched_ids: list[str] = []
        unmatched: list[TopMatch] = []

        for match in top_matches:
            normalized_filename = _normalize_relative_path(match.filename or "")
            rag_relative_path = rag_by_file_id.get(match.vector_file_id)
            if rag_relative_path is None and normalized_filename:
                rag_relative_path = rag_by_path.get(normalized_filename)

            if rag_relative_path is None:
                unmatched.append(match)
                continue

            mapped_id = input_mapping.get(rag_relative_path)
            if mapped_id is None:
                unmatched.append(match)
                continue

            match.matched_input_file_id = mapped_id
            matched_ids.append(mapped_id)

        return matched_ids, unmatched

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped
