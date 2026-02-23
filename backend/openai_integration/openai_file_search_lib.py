from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from openai import OpenAI

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "input_files_manifest.json"


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
class UploadedInputFile:
    relative_path: str
    file_id: str


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
    uploaded_files: list[UploadedInputFile]
    top_matches: list[TopMatch]
    unmatched_top_matches: list[TopMatch]


class OpenAIFileSearchClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        vector_store_id: str | None = None,
        env_file: Path | None = None,
    ) -> None:
        root_env = Path(__file__).resolve().parent.parent.parent / ".env"
        candidate_env = env_file or root_env

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
    ) -> TwoStageSearchResult:
        uploaded_files = self.load_uploaded_files_manifest(manifest_path)
        uploaded_file_ids = [item.file_id for item in uploaded_files]

        first_response = self._create_response_request(
            question=question,
            file_ids=uploaded_file_ids,
            system_prompt=system_prompt,
            model=model,
        )
        first_response_id = getattr(first_response, "id", "")

        top_matches = self._search_top_matches(question=question, top_k=top_k)
        matched_top_file_ids, unmatched_top_matches = self._map_top_matches_to_uploaded_files(
            top_matches=top_matches,
            uploaded_files=uploaded_files,
        )

        second_file_ids = self._dedupe_preserve_order(uploaded_file_ids + matched_top_file_ids)
        second_response = self._create_response_request(
            question=question,
            file_ids=second_file_ids,
            system_prompt=system_prompt,
            model=model,
        )
        second_response_id = getattr(second_response, "id", "")
        response_text = getattr(second_response, "output_text", "") or ""

        return TwoStageSearchResult(
            response_text=response_text,
            first_response_id=first_response_id,
            second_response_id=second_response_id,
            uploaded_files=uploaded_files,
            top_matches=top_matches,
            unmatched_top_matches=unmatched_top_matches,
        )

    def load_uploaded_files_manifest(self, manifest_path: Path) -> list[UploadedInputFile]:
        if not manifest_path.exists():
            raise ValueError(
                "Input files manifest not found. Run uploader first: "
                "python -m openai_integration.openai_input_files_uploader"
            )

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc

        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Manifest must include non-empty files list")

        uploaded: list[UploadedInputFile] = []
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("Manifest file entry must be object")
            relative_path = item.get("relative_path")
            file_id = item.get("file_id")
            if not isinstance(relative_path, str) or not relative_path.strip():
                raise ValueError("Manifest file entry missing relative_path")
            if not isinstance(file_id, str) or not file_id.strip():
                raise ValueError("Manifest file entry missing file_id")
            uploaded.append(
                UploadedInputFile(
                    relative_path=_normalize_relative_path(relative_path),
                    file_id=file_id.strip(),
                )
            )

        return uploaded

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

    def _search_top_matches(self, *, question: str, top_k: int) -> list[TopMatch]:
        top_k = max(1, top_k)
        search_results = self._client.vector_stores.search(
            self._vector_store_id,
            query=question,
            max_num_results=top_k,
        )
        matches: list[TopMatch] = []
        for result in search_results:
            matches.append(
                TopMatch(
                    vector_file_id=getattr(result, "file_id", ""),
                    filename=getattr(result, "filename", None),
                    score=getattr(result, "score", None),
                    matched_input_file_id=None,
                )
            )
        return matches

    def _map_top_matches_to_uploaded_files(
        self,
        *,
        top_matches: list[TopMatch],
        uploaded_files: list[UploadedInputFile],
    ) -> tuple[list[str], list[TopMatch]]:
        mapping = {
            _normalize_relative_path(item.relative_path): item.file_id for item in uploaded_files
        }
        matched_ids: list[str] = []
        unmatched: list[TopMatch] = []

        for match in top_matches:
            normalized_name = _normalize_relative_path(match.filename or "")
            mapped_id = mapping.get(normalized_name)
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
