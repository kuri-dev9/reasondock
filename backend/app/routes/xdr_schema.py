from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import ConversationDataset, RcaDataset, XdrFieldKeyword, XdrFieldSchema, XdrSchemaProfile
from app.qie.datasets import dataset_manager
from app.qie.schema.spec_loader import FieldSpec, load_lte_call_kpi_spec

router = APIRouter(prefix="/api/rca/xdr-schema", tags=["xdr-schema"])
logger = logging.getLogger(__name__)


_RICH_TAXONOMY: dict[str, dict] = {
    "IMSI": {
        "category": "User",
        "role": "subscriber_identifier",
        "description": "가입자 식별자",
        "db_type": "VARCHAR2",
        "size": 16,
        "aliases": ["가입자", "subscriber", "UE", "사용자", "단말"],
        "importance": "critical",
        "groupable": True,
        "filterable": True,
        "searchable": True,
        "joinable": True,
        "pii": True,
        "active": True,
    },
    "IMEI": {
        "category": "User",
        "role": "device_identifier",
        "description": "단말 식별자",
        "db_type": "VARCHAR2",
        "size": 16,
        "aliases": ["단말", "device", "기기", "terminal"],
        "importance": "high",
        "groupable": True,
        "filterable": True,
        "searchable": True,
        "joinable": True,
        "pii": True,
        "active": True,
    },
    "MDN": {
        "category": "User",
        "role": "subscriber_identifier",
        "description": "전화번호",
        "db_type": "VARCHAR2",
        "aliases": ["전화번호", "번호", "MSISDN"],
        "importance": "medium",
        "groupable": True,
        "filterable": True,
        "searchable": True,
        "joinable": True,
        "pii": True,
        "active": False,
    },
    "SummaryCreateTime": {
        "category": "Summary",
        "role": "timestamp",
        "description": "xDR 생성 시간",
        "db_type": "TIME",
        "aliases": ["시간", "timestamp", "생성시간", "발생시간"],
        "importance": "critical",
        "groupable": True,
        "filterable": True,
        "sortable": True,
        "time_series": True,
        "active": True,
    },
    "call_type": {
        "category": "Procedure",
        "role": "procedure",
        "description": "호 절차 유형",
        "aliases": ["call type", "호유형", "콜타입", "절차", "procedure", "attach", "tau", "service request"],
        "importance": "critical",
        "groupable": True,
        "filterable": True,
        "categorical": True,
        "active": True,
    },
    "attempt_flag": {
        "category": "Status",
        "role": "status_flag",
        "description": "시도 여부",
        "aliases": ["attempt", "시도", "호시도"],
        "importance": "high",
        "filterable": True,
        "categorical": True,
        "boolean_like": True,
        "active": True,
    },
    "success_flag": {
        "category": "Status",
        "role": "status_flag",
        "description": "성공 여부",
        "aliases": ["success", "성공", "실패", "failure", "drop"],
        "importance": "critical",
        "filterable": True,
        "groupable": True,
        "categorical": True,
        "boolean_like": True,
        "active": True,
    },
    "drop_flag": {
        "category": "Status",
        "role": "status_flag",
        "description": "절단 여부",
        "aliases": ["drop", "절단", "call drop"],
        "importance": "high",
        "filterable": True,
        "groupable": True,
        "categorical": True,
        "active": True,
    },
    "first_error_interface_protocol": {
        "category": "Failure",
        "role": "protocol",
        "description": "최초 오류 인터페이스 프로토콜",
        "aliases": ["interface", "protocol", "인터페이스", "프로토콜", "S1AP", "S6a", "Diameter", "GTP", "NAS"],
        "importance": "critical",
        "groupable": True,
        "filterable": True,
        "categorical": True,
        "active": True,
    },
    "first_error_cause": {
        "category": "Failure",
        "role": "cause_code",
        "description": "최초 오류 원인 코드",
        "aliases": ["cause", "error cause", "실패원인", "오류원인", "cause code"],
        "importance": "critical",
        "groupable": True,
        "filterable": True,
        "categorical": True,
        "active": True,
    },
    "last_error_cause": {
        "category": "Failure",
        "role": "cause_code",
        "description": "최종 오류 원인 코드",
        "aliases": ["last cause", "최종원인", "마지막원인"],
        "importance": "high",
        "groupable": True,
        "filterable": True,
        "categorical": True,
        "active": True,
    },
    "MME_ID": {
        "category": "Network",
        "role": "network_identifier",
        "description": "MME 식별자",
        "aliases": ["MME", "MME ID", "core node"],
        "importance": "high",
        "groupable": True,
        "filterable": True,
        "joinable": True,
        "active": True,
    },
    "SGW_ID": {
        "category": "Network",
        "role": "network_identifier",
        "description": "SGW 식별자",
        "aliases": ["SGW", "Serving Gateway"],
        "importance": "medium",
        "groupable": True,
        "filterable": True,
        "joinable": True,
        "active": True,
    },
    "APN": {
        "category": "Configuration",
        "role": "state",
        "description": "APN 정보",
        "aliases": ["APN", "access point", "pdn"],
        "importance": "medium",
        "groupable": True,
        "filterable": True,
        "categorical": True,
        "active": False,
    },
}

_SEMANTIC_BOOL_FIELDS = (
    "groupable",
    "filterable",
    "searchable",
    "joinable",
    "pii",
    "sortable",
    "time_series",
    "categorical",
    "boolean_like",
)


async def ensure_defaults(db: AsyncSession) -> None:
    result = await db.execute(select(XdrSchemaProfile).limit(1))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = XdrSchemaProfile(
            name="기본 xDR 스키마",
            description="spec 기반 기본 xDR field taxonomy",
            is_default=True,
            is_active=True,
        )
        db.add(profile)
        await db.flush()

    await _ensure_spec_fields_for_all_profiles(db)
    await db.commit()


async def _ensure_spec_fields_for_all_profiles(db: AsyncSession) -> None:
    profiles = (await db.execute(select(XdrSchemaProfile))).scalars().all()
    specs = load_lte_call_kpi_spec()
    for profile in profiles:
        await _ensure_spec_fields(db, profile.id, specs)


async def _ensure_spec_fields(db: AsyncSession, schema_id: int, specs: tuple[FieldSpec, ...]) -> None:
    existing_result = await db.execute(
        select(XdrFieldSchema)
        .where(XdrFieldSchema.schema_id == schema_id)
        .options(selectinload(XdrFieldSchema.keywords))
    )
    existing = {field.field_name.lower(): field for field in existing_result.scalars().all()}
    spec_keys = {spec.name.lower() for spec in specs}
    for spec in specs:
        rich = _RICH_TAXONOMY.get(spec.name)
        field = existing.get(spec.name.lower())
        if field is None:
            field = XdrFieldSchema(
                schema_id=schema_id,
                field_name=spec.name,
                description=(rich or {}).get("description") or spec.description or spec.name,
                is_active=bool((rich or {}).get("active", False)),
                is_custom=False,
            )
            db.add(field)
            await db.flush()
            existing[spec.name.lower()] = field
            await _replace_aliases(db, field, (rich or {}).get("aliases", []))
        elif not field.is_custom and field.field_name != spec.name:
            field.field_name = spec.name
        _apply_spec_metadata(field, spec, rich, overwrite_semantic=_is_semantic_empty(field))
    for key, field in existing.items():
        if key not in spec_keys and not field.is_custom:
            field.is_active = False
            field.spec_section = field.spec_section or "Legacy"
            field.spec_sheet = field.spec_sheet or "Legacy"
            field.tree_path = field.tree_path or ["Legacy"]
            field.category = field.category or "Legacy"
            field.importance = field.importance or "low"


def _is_semantic_empty(field: XdrFieldSchema) -> bool:
    return (
        field.spec_no is None
        and field.spec_section is None
        and field.tree_path is None
        and field.category is None
        and field.role is None
        and field.db_type is None
    )


def _apply_spec_metadata(
    field: XdrFieldSchema,
    spec: FieldSpec,
    rich: dict | None,
    *,
    overwrite_semantic: bool,
) -> None:
    field.spec_no = spec.no
    field.spec_index = spec.index
    field.spec_sheet = spec.sheet_name
    field.spec_section = spec.section
    field.tree_path = list(spec.tree_path)
    if not field.db_type:
        field.db_type = (rich or {}).get("db_type") or spec.collect_type
    if not field.description:
        field.description = (rich or {}).get("description") or spec.description or spec.name
    if overwrite_semantic:
        field.category = (rich or {}).get("category") or spec.section
        field.role = (rich or {}).get("role")
        field.db_type = (rich or {}).get("db_type") or spec.collect_type
        field.size = (rich or {}).get("size")
        field.importance = (rich or {}).get("importance", "low")
        if rich:
            field.is_active = bool(rich.get("active", False))
        for key in _SEMANTIC_BOOL_FIELDS:
            setattr(field, key, bool((rich or {}).get(key, False)))
        field.semantic_metadata = {
            key: value
            for key, value in (rich or {}).items()
            if key not in {"aliases", "description", "active", "category", "role", "db_type", "size", "importance", *_SEMANTIC_BOOL_FIELDS}
        } or None


async def _replace_aliases(db: AsyncSession, field: XdrFieldSchema, aliases: list[str]) -> None:
    seen = set()
    for alias in aliases:
        alias = str(alias).strip()
        key = alias.lower()
        if not alias or key in seen:
            continue
        seen.add(key)
        db.add(XdrFieldKeyword(field_id=field.id, keyword=alias))


async def active_schema_id(db: AsyncSession) -> int:
    await ensure_defaults(db)
    result = await db.execute(
        select(XdrSchemaProfile).where(XdrSchemaProfile.is_active == True).order_by(XdrSchemaProfile.id).limit(1)
    )
    profile = result.scalar_one_or_none()
    if profile:
        return profile.id
    result = await db.execute(select(XdrSchemaProfile).order_by(XdrSchemaProfile.id).limit(1))
    profile = result.scalar_one()
    profile.is_active = True
    await db.commit()
    return profile.id


def _field_to_dict(field: XdrFieldSchema) -> dict:
    aliases = [keyword.keyword for keyword in field.keywords]
    return {
        "id": field.id,
        "schema_id": field.schema_id,
        "field_name": field.field_name,
        "description": field.description,
        "is_active": field.is_active,
        "is_custom": field.is_custom,
        "spec_no": field.spec_no,
        "spec_index": field.spec_index,
        "spec_sheet": field.spec_sheet,
        "spec_section": field.spec_section,
        "tree_path": field.tree_path or ([field.spec_section] if field.spec_section else []),
        "category": field.category,
        "role": field.role,
        "db_type": field.db_type,
        "size": field.size,
        "importance": field.importance,
        "groupable": field.groupable,
        "filterable": field.filterable,
        "searchable": field.searchable,
        "joinable": field.joinable,
        "pii": field.pii,
        "sortable": field.sortable,
        "time_series": field.time_series,
        "categorical": field.categorical,
        "boolean_like": field.boolean_like,
        "semantic_metadata": field.semantic_metadata,
        "keywords": aliases,
        "aliases": aliases,
    }


async def _dataset_count(db: AsyncSession, schema_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(RcaDataset).where(RcaDataset.schema_id == schema_id)
    )
    return int(result.scalar_one() or 0)


async def _profile_to_dict(db: AsyncSession, profile: XdrSchemaProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "is_default": profile.is_default,
        "is_active": profile.is_active,
        "dataset_count": await _dataset_count(db, profile.id),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


async def _load_profile(db: AsyncSession, schema_id: int) -> XdrSchemaProfile | None:
    result = await db.execute(select(XdrSchemaProfile).where(XdrSchemaProfile.id == schema_id))
    return result.scalar_one_or_none()


async def _load_field(db: AsyncSession, field_id: int) -> XdrFieldSchema | None:
    result = await db.execute(
        select(XdrFieldSchema)
        .where(XdrFieldSchema.id == field_id)
        .options(selectinload(XdrFieldSchema.keywords))
    )
    return result.scalar_one_or_none()


async def _clone_fields(db: AsyncSession, source_schema_id: int, target_schema_id: int) -> None:
    result = await db.execute(
        select(XdrFieldSchema)
        .where(XdrFieldSchema.schema_id == source_schema_id)
        .options(selectinload(XdrFieldSchema.keywords))
        .order_by(XdrFieldSchema.is_custom, XdrFieldSchema.id)
    )
    for source in result.scalars().all():
        field = XdrFieldSchema(
            schema_id=target_schema_id,
            field_name=source.field_name,
            description=source.description,
            is_active=source.is_active,
            is_custom=source.is_custom,
            spec_no=source.spec_no,
            spec_index=source.spec_index,
            spec_sheet=source.spec_sheet,
            spec_section=source.spec_section,
            tree_path=source.tree_path,
            category=source.category,
            role=source.role,
            db_type=source.db_type,
            size=source.size,
            importance=source.importance,
            groupable=source.groupable,
            filterable=source.filterable,
            searchable=source.searchable,
            joinable=source.joinable,
            pii=source.pii,
            sortable=source.sortable,
            time_series=source.time_series,
            categorical=source.categorical,
            boolean_like=source.boolean_like,
            semantic_metadata=source.semantic_metadata,
        )
        db.add(field)
        await db.flush()
        for keyword in source.keywords:
            db.add(XdrFieldKeyword(field_id=field.id, keyword=keyword.keyword))


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db)):
    await ensure_defaults(db)
    result = await db.execute(select(XdrSchemaProfile).order_by(XdrSchemaProfile.id))
    return [await _profile_to_dict(db, profile) for profile in result.scalars().all()]


@router.get("/profiles/active")
async def get_active_profile(db: AsyncSession = Depends(get_db)):
    schema_id = await active_schema_id(db)
    profile = await _load_profile(db, schema_id)
    return await _profile_to_dict(db, profile)


@router.post("/profiles")
async def create_profile(body: dict, db: AsyncSession = Depends(get_db)):
    await ensure_defaults(db)
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name이 필요합니다")
    source_schema_id = body.get("source_schema_id")
    if source_schema_id is None:
        source_schema_id = await active_schema_id(db)
    source = await _load_profile(db, int(source_schema_id))
    if not source:
        raise HTTPException(status_code=404, detail="복제할 스키마를 찾을 수 없습니다")

    profile = XdrSchemaProfile(
        name=name,
        description=str(body.get("description", ""))[:255] or None,
        is_default=False,
        is_active=False,
    )
    db.add(profile)
    try:
        await db.flush()
        await _clone_fields(db, source.id, profile.id)
        await db.commit()
        await db.refresh(profile)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 존재하는 스키마 이름입니다") from exc
    await db.refresh(profile)
    return await _profile_to_dict(db, profile)


@router.patch("/profiles/{schema_id}")
async def update_profile(schema_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    profile = await _load_profile(db, schema_id)
    if not profile:
        raise HTTPException(status_code=404, detail="스키마를 찾을 수 없습니다")
    if "name" in body:
        name = str(body["name"]).strip()
        if not name:
            raise HTTPException(status_code=400, detail="name이 필요합니다")
        profile.name = name
    if "description" in body:
        profile.description = str(body["description"])[:255] or None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 존재하는 스키마 이름입니다") from exc
    return await _profile_to_dict(db, profile)


@router.patch("/profiles/{schema_id}/active")
async def set_active_profile(schema_id: int, db: AsyncSession = Depends(get_db)):
    profile = await _load_profile(db, schema_id)
    if not profile:
        raise HTTPException(status_code=404, detail="스키마를 찾을 수 없습니다")
    await db.execute(update(XdrSchemaProfile).values(is_active=False))
    profile.is_active = True
    await db.commit()
    await db.refresh(profile)
    return await _profile_to_dict(db, profile)


@router.delete("/profiles/{schema_id}")
async def delete_profile(schema_id: int, db: AsyncSession = Depends(get_db)):
    profile = await _load_profile(db, schema_id)
    if not profile:
        raise HTTPException(status_code=404, detail="스키마를 찾을 수 없습니다")
    if profile.is_default:
        raise HTTPException(status_code=403, detail="기본 스키마는 삭제할 수 없습니다")

    datasets = (await db.execute(select(RcaDataset).where(RcaDataset.schema_id == schema_id))).scalars().all()
    deleted_dataset_ids = []
    for dataset in datasets:
        await dataset_manager.delete_dataset(dataset.dataset_id)
        deleted_dataset_ids.append(dataset.dataset_id)
        attachments = await db.execute(
            select(ConversationDataset).where(ConversationDataset.dataset_id == dataset.dataset_id)
        )
        for attachment in attachments.scalars().all():
            await db.delete(attachment)
        await db.delete(dataset)

    was_active = profile.is_active
    await db.delete(profile)
    await db.commit()
    if was_active:
        fallback_id = await active_schema_id(db)
        logger.info("삭제된 active xDR schema를 기본 후보로 전환: %s", fallback_id)
    return {"deleted": schema_id, "deleted_datasets": deleted_dataset_ids}


@router.get("")
async def list_schema(schema_id: int | None = None, db: AsyncSession = Depends(get_db)):
    await ensure_defaults(db)
    target_schema_id = schema_id or await active_schema_id(db)
    result = await db.execute(
        select(XdrFieldSchema)
        .where(XdrFieldSchema.schema_id == target_schema_id)
        .options(selectinload(XdrFieldSchema.keywords))
        .order_by(XdrFieldSchema.is_custom, XdrFieldSchema.spec_index.is_(None), XdrFieldSchema.spec_index, XdrFieldSchema.id)
    )
    return [_field_to_dict(field) for field in result.scalars().all()]


@router.post("")
async def add_field(body: dict, db: AsyncSession = Depends(get_db)):
    schema_id = int(body.get("schema_id") or await active_schema_id(db))
    if not await _load_profile(db, schema_id):
        raise HTTPException(status_code=404, detail="스키마를 찾을 수 없습니다")
    field_name = str(body.get("field_name", "")).strip()
    if not field_name:
        raise HTTPException(status_code=400, detail="field_name이 필요합니다")

    field = XdrFieldSchema(
        schema_id=schema_id,
        field_name=field_name,
        description=str(body.get("description", ""))[:255] or None,
        is_active=True,
        is_custom=True,
        spec_sheet=str(body.get("spec_sheet", "Custom"))[:100] or "Custom",
        spec_section=str(body.get("spec_section", "Custom"))[:100] or "Custom",
        tree_path=body.get("tree_path") if isinstance(body.get("tree_path"), list) else ["Custom"],
        category=str(body.get("category", "Custom"))[:100] or "Custom",
        role=str(body.get("role", "")).strip()[:80] or None,
        db_type=str(body.get("db_type", "string"))[:50] or "string",
        importance=str(body.get("importance", "low"))[:20] or "low",
    )
    _apply_field_body(field, body, allow_name=False)
    db.add(field)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 존재하는 필드입니다") from exc
    loaded = await _load_field(db, field.id)
    return _field_to_dict(loaded or field)


@router.patch("/{field_id}")
async def update_field(field_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    field = await _load_field(db, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="필드를 찾을 수 없습니다")
    if "field_name" in body:
        if not field.is_custom:
            raise HTTPException(status_code=403, detail="기본 필드의 이름은 변경할 수 없습니다")
        field_name = str(body["field_name"]).strip()
        if not field_name:
            raise HTTPException(status_code=400, detail="field_name이 필요합니다")
        field.field_name = field_name
    if "description" in body:
        field.description = str(body["description"])[:255] or None
    if "is_active" in body:
        field.is_active = bool(body["is_active"])
    _apply_field_body(field, body, allow_name=False)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 존재하는 필드입니다") from exc
    loaded = await _load_field(db, field_id)
    return _field_to_dict(loaded or field)


def _apply_field_body(field: XdrFieldSchema, body: dict, *, allow_name: bool) -> None:
    text_fields = {
        "spec_sheet": 100,
        "spec_section": 100,
        "category": 100,
        "role": 80,
        "db_type": 50,
        "importance": 20,
    }
    for key, limit in text_fields.items():
        if key in body:
            value = str(body[key]).strip()
            setattr(field, key, value[:limit] or None)
    if "size" in body:
        try:
            field.size = int(body["size"]) if body["size"] not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="size는 숫자여야 합니다")
    for key in _SEMANTIC_BOOL_FIELDS:
        if key in body:
            setattr(field, key, bool(body[key]))
    if "semantic_metadata" in body:
        field.semantic_metadata = body["semantic_metadata"] if isinstance(body["semantic_metadata"], dict) else None
    if "tree_path" in body:
        if body["tree_path"] is None:
            field.tree_path = None
        elif isinstance(body["tree_path"], list):
            parts = [str(part).strip()[:100] for part in body["tree_path"] if str(part).strip()]
            field.tree_path = parts or None
        else:
            raise HTTPException(status_code=400, detail="tree_path는 배열이어야 합니다")


@router.delete("/{field_id}")
async def delete_field(field_id: int, db: AsyncSession = Depends(get_db)):
    field = await _load_field(db, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="필드를 찾을 수 없습니다")
    if not field.is_custom:
        raise HTTPException(status_code=403, detail="기본 필드는 삭제할 수 없습니다")
    await db.delete(field)
    await db.commit()
    return {"deleted": field_id}


@router.post("/{field_id}/keywords")
async def add_keyword(field_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    keyword = str(body.get("keyword", "")).strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword가 비어있습니다")
    field = await _load_field(db, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="필드를 찾을 수 없습니다")
    db.add(XdrFieldKeyword(field_id=field_id, keyword=keyword))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="이미 존재하는 키워드입니다") from exc
    return {"field_id": field_id, "keyword": keyword}


@router.delete("/{field_id}/keywords/{keyword}")
async def delete_keyword(field_id: int, keyword: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(XdrFieldKeyword).where(
            XdrFieldKeyword.field_id == field_id,
            XdrFieldKeyword.keyword == keyword,
        )
    )
    field_keyword = result.scalar_one_or_none()
    if not field_keyword:
        raise HTTPException(status_code=404, detail="키워드를 찾을 수 없습니다")
    await db.delete(field_keyword)
    await db.commit()
    return {"deleted": keyword}
