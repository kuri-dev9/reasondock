import logging
import re
from app.api.schemas import ProcessRequest, DocumentProcessResult
from app.core import structure_detector
from app.core.normalizer import Normalizer
from app.adapters.backend_client import _default_client
from app.adapters.uce_client import call_uce_denoise
from app.config import settings

logger = logging.getLogger(__name__)

_normalizer = Normalizer(_default_client)

_NORMALIZATION_CANDIDATES = {"plain_text", "mixed", "unknown", "log"}


async def process(request: ProcessRequest) -> DocumentProcessResult:
    # 빈 content는 즉시 fallback
    if not request.content.strip():
        return _make_result(
            request=request,
            normalized_content=request.content,
            structure_type="unknown",
            confidence=0.0,
            normalization_applied=False,
            normalization_model=None,
        )

    structure_type, confidence = structure_detector.detect(request.filename, request.content)

    normalization_skipped_reason = _normalization_skipped_reason(
        request=request,
        structure_type=structure_type,
        confidence=confidence,
    )
    needs_normalization = (
        normalization_skipped_reason is None
    )

    normalized_content = request.content
    normalization_applied = False
    normalization_model = None
    denoised_content = None

    if needs_normalization:
        content_for_normalization = request.content
        if settings.uce_denoise_enabled:
            denoised = await call_uce_denoise(
                content=request.content,
                content_type=_structure_to_content_type(structure_type),
                document_id=request.document_id,
                title=request.filename,
            )
            if denoised:
                content_for_normalization = denoised
                denoised_content = denoised

        try:
            normalized_content, normalization_model = await _normalizer.normalize(
                content=content_for_normalization,
                structure_type=structure_type,
                filename=request.filename,
                backend_normalize_url=request.options.backend_normalize_url,
                model=request.options.normalization_model,
            )
            normalization_applied = (
                normalized_content.strip() != request.content.strip()
                or (denoised_content is not None and denoised_content.strip() != request.content.strip())
                or bool(re.search(r"^#{1,3}\s+\S", normalized_content, re.MULTILINE))
            )
        except Exception as e:
            logger.warning(
                "normalization 실패, 원본 사용 (document_id=%s): %s",
                request.document_id, e,
            )
            normalized_content = request.content

    return _make_result(
        request=request,
        normalized_content=normalized_content,
        structure_type=structure_type,
        confidence=confidence,
        normalization_applied=normalization_applied,
        normalization_model=normalization_model,
        normalization_skipped_reason=normalization_skipped_reason,
        denoised_content=denoised_content,
    )


def _normalization_skipped_reason(
    request: ProcessRequest,
    structure_type: str,
    confidence: float,
) -> str | None:
    if not request.options.normalization_enabled:
        return "normalization_disabled"
    if confidence > settings.dpe_normalization_min_confidence:
        return "confidence_above_threshold"
    if structure_type not in _NORMALIZATION_CANDIDATES:
        return "structure_not_candidate"
    if len(request.content) > settings.dpe_normalization_max_chars:
        return "content_too_large"
    return None


def _structure_to_content_type(structure_type: str) -> str:
    if structure_type == "markdown":
        return "markdown"
    if structure_type in {"code", "json", "yaml", "log"}:
        return structure_type
    return "text"


def _make_result(
    request: ProcessRequest,
    normalized_content: str,
    structure_type: str,
    confidence: float,
    normalization_applied: bool,
    normalization_model: str | None,
    normalization_skipped_reason: str | None = None,
    denoised_content: str | None = None,
) -> DocumentProcessResult:
    chunk_strategy = _select_chunk_strategy(structure_type, normalization_applied)
    retrieval_hints = _build_retrieval_hints(normalized_content, structure_type, normalization_applied)
    content_type = "dpe_ir" if normalization_applied else _structure_to_content_type(structure_type)
    return DocumentProcessResult(
        document_id=request.document_id,
        normalized_content=normalized_content,
        structure_type=structure_type,
        structure_confidence=round(confidence, 4),
        chunk_strategy=chunk_strategy,
        normalization_applied=normalization_applied,
        normalization_model=normalization_model,
        normalization_skipped_reason=normalization_skipped_reason,
        retrieval_hints=retrieval_hints,
        content_type=content_type,
        denoised_content=denoised_content,
    )


def _select_chunk_strategy(structure_type: str, normalization_applied: bool) -> str:
    if normalization_applied or structure_type == "markdown":
        return "heading-aware"
    if structure_type == "code":
        return "heading-aware"
    if structure_type == "log":
        return "log-window"
    if structure_type == "table":
        return "table-row"
    if structure_type in {"json", "yaml"}:
        return "json-object"
    if structure_type == "mixed":
        return "semantic-window"
    return "sliding-window"


def _build_retrieval_hints(
    content: str,
    structure_type: str,
    normalization_applied: bool,
) -> list[str]:
    hints: list[str] = []

    if structure_type == "markdown" or normalization_applied:
        if re.search(r"^#{1,3}\s+\S", content, re.MULTILINE):
            hints.append("heading")

    # 대문자 시작 단어 (entity 후보) — 영문 기준
    if re.search(r"\b[A-Z][A-Za-z]{2,}\b", content):
        hints.append("entity")

    if "|" in content and re.search(r"\|[-\s|]+\|", content):
        hints.append("table")

    if re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", content):
        hints.append("timestamp")

    if "```" in content:
        hints.append("code_block")

    return hints
