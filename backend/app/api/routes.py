from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LVProject, LVProjectPosition, Product
from ..schemas import (
    CompatibilityCheckRequest,
    CompatibilityIssue,
    DuplicateInfo,
    ExportOfferRequest,
    ExportPreviewResponse,
    ExportWarning,
    HealthResponse,
    LVPosition,
    OfferLine,
    ParseLVResponse,
    PositionSuggestions,
    ProductSearchResult,
    ProductSuggestion,
    ProjectDetailResponse,
    ProjectSummary,
    SuggestionsRequest,
    SuggestionsResponse,
    TechnicalParameters,
)
import logging

from ..config import settings
from ..services.ai_interpreter import enrich_positions_with_parameters
from ..services.compatibility import check_compatibility
from ..services.llm_parser import parse_lv_with_llm
from ..services.match_validator import validate_matches
from ..services.matcher import load_active_products, suggest_products_for_position
from ..services.offer_export import build_offer_pdf, now_metadata
from ..services.pdf_parser import extract_positions_from_pdf

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["tiefbaux"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


def _fallback_parse(pdf_bytes: bytes) -> list[LVPosition]:
    """Regex-based parsing with optional LLM enrichment. Handles LLM errors gracefully."""
    positions = extract_positions_from_pdf(pdf_bytes)
    try:
        positions = enrich_positions_with_parameters(positions)
    except Exception as exc:
        logger.warning("LLM enrichment failed, using raw regex positions: %s", exc)
    return positions


def _reconstruct_positions(db_positions: list[LVProjectPosition]) -> list[LVPosition]:
    """Reconstruct LVPosition objects from stored DB rows."""
    result: list[LVPosition] = []
    for dbp in db_positions:
        params = TechnicalParameters()
        if dbp.parameters_json:
            try:
                params = TechnicalParameters(**json.loads(dbp.parameters_json))
            except Exception:
                pass
        result.append(LVPosition(
            id=dbp.position_id,
            ordnungszahl=dbp.ordnungszahl,
            description=dbp.description,
            raw_text=dbp.raw_text,
            quantity=dbp.quantity,
            unit=dbp.unit,
            billable=dbp.billable,
            position_type=dbp.position_type,
            parameters=params,
        ))
    return result


def _store_project(
    db: Session, content_hash: str, filename: str | None, positions: list[LVPosition],
) -> LVProject:
    """Persist parsed LV positions to the database."""
    billable = sum(1 for p in positions if p.billable)
    service = sum(1 for p in positions if p.position_type == "dienstleistung")

    project = LVProject(
        content_hash=content_hash,
        filename=filename,
        total_positions=len(positions),
        billable_positions=billable,
        service_positions=service,
    )
    db.add(project)
    db.flush()

    for pos in positions:
        db.add(LVProjectPosition(
            project_id=project.id,
            position_id=pos.id,
            ordnungszahl=pos.ordnungszahl,
            description=pos.description,
            raw_text=pos.raw_text,
            quantity=pos.quantity,
            unit=pos.unit,
            billable=pos.billable,
            position_type=pos.position_type,
            parameters_json=pos.parameters.model_dump_json() if pos.parameters else None,
        ))
    db.commit()
    return project


@router.post("/parse-lv", response_model=ParseLVResponse)
async def parse_lv(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ParseLVResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported in MVP")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # Check for existing analysis
    existing = db.scalar(select(LVProject).where(LVProject.content_hash == content_hash))
    if existing:
        logger.info("Duplicate LV detected (hash=%s, project_id=%d)", content_hash[:12], existing.id)
        positions = _reconstruct_positions(existing.positions)
        return ParseLVResponse(
            positions=positions,
            total_positions=existing.total_positions,
            billable_positions=existing.billable_positions,
            service_positions=existing.service_positions,
            duplicate=DuplicateInfo(
                is_duplicate=True,
                project_id=existing.id,
                project_name=existing.project_name,
                created_at=existing.created_at,
                total_positions=existing.total_positions,
            ),
        )

    # New LV — parse normally
    if settings.gemini_api_key:
        try:
            positions = parse_lv_with_llm(pdf_bytes)
        except Exception as exc:
            logger.warning("LLM parsing failed, falling back to regex: %s", exc)
            positions = _fallback_parse(pdf_bytes)
    else:
        positions = _fallback_parse(pdf_bytes)

    # Store for future duplicate detection
    try:
        project = _store_project(db, content_hash, file.filename, positions)
        duplicate_info = DuplicateInfo(is_duplicate=False, project_id=project.id)
    except Exception as exc:
        logger.warning("Failed to store LV project: %s", exc)
        duplicate_info = DuplicateInfo(is_duplicate=False)

    return ParseLVResponse(
        positions=positions,
        total_positions=len(positions),
        billable_positions=sum(1 for p in positions if p.billable),
        service_positions=sum(1 for p in positions if p.position_type == "dienstleistung"),
        duplicate=duplicate_info,
    )


def _compute_confidence(suggestion: ProductSuggestion, llm_validated: bool) -> str:
    if suggestion.score > 60 and llm_validated:
        return "high"
    if suggestion.score >= 35 and llm_validated:
        return "medium"
    return "low"


@router.post("/suggestions", response_model=SuggestionsResponse)
def get_suggestions(request: SuggestionsRequest, db: Session = Depends(get_db)) -> SuggestionsResponse:
    products = load_active_products(db)

    # Phase 1: Score all positions
    scored_pairs: list[tuple[LVPosition, list[ProductSuggestion]]] = []
    for position in request.positions:
        suggestions = suggest_products_for_position(db, position, products=products)
        scored_pairs.append((position, suggestions))

    # Phase 2: LLM match validation
    pairs_with_suggestions = [
        (pos, sugs) for pos, sugs in scored_pairs if sugs
    ]
    validated_map: dict[str, list[ProductSuggestion]] = {}
    llm_validated = False
    if pairs_with_suggestions:
        validated = validate_matches(pairs_with_suggestions)
        validated_map = {pos.id: sugs for pos, sugs in validated}
        llm_validated = True

    # Phase 3: Assemble response with confidence
    position_suggestions: list[PositionSuggestions] = []
    selected_for_check: list[tuple[LVPosition, object]] = []

    for position, original_suggestions in scored_pairs:
        final_suggestions = validated_map.get(position.id, original_suggestions)
        for s in final_suggestions:
            s.confidence = _compute_confidence(s, llm_validated)
        position_suggestions.append(
            PositionSuggestions(
                position_id=position.id,
                ordnungszahl=position.ordnungszahl,
                description=position.description,
                suggestions=final_suggestions,
            )
        )
        if final_suggestions:
            selected_for_check.append((position, final_suggestions[0]))

    compatibility_issues = check_compatibility(selected_for_check)

    return SuggestionsResponse(suggestions=position_suggestions, compatibility_issues=compatibility_issues)



@router.post("/suggestions/single", response_model=PositionSuggestions)
def get_single_suggestions(position: LVPosition, db: Session = Depends(get_db)) -> PositionSuggestions:
    suggestions = suggest_products_for_position(db, position)
    return PositionSuggestions(
        position_id=position.id,
        ordnungszahl=position.ordnungszahl,
        description=position.description,
        suggestions=suggestions,
    )


def _resolve_unit_price(product: Product, quantity: float) -> float | None:
    if quantity >= 100 and product.staffelpreis_ab_100 is not None:
        return product.staffelpreis_ab_100
    if quantity >= 50 and product.staffelpreis_ab_50 is not None:
        return product.staffelpreis_ab_50
    if quantity >= 10 and product.staffelpreis_ab_10 is not None:
        return product.staffelpreis_ab_10
    return product.vk_listenpreis_netto


def _build_offer_lines(
    request: ExportOfferRequest, db: Session
) -> tuple[list[OfferLine], list[ExportWarning]]:
    """Build offer lines and collect warnings about skipped/problematic positions."""
    positions_by_id = {position.id: position for position in request.positions}
    lines: list[OfferLine] = []
    warnings: list[ExportWarning] = []

    # Check for material positions without article assignment (skip Dienstleistungen)
    for position in request.positions:
        if position.id not in request.selected_article_ids and position.position_type != "dienstleistung":
            warnings.append(ExportWarning(
                position_id=position.id,
                ordnungszahl=position.ordnungszahl,
                reason="Kein Artikel zugeordnet",
            ))

    for position_id, artikel_id in request.selected_article_ids.items():
        position = positions_by_id.get(position_id)
        if position is None:
            continue

        product = db.scalar(select(Product).where(Product.artikel_id == artikel_id))
        if product is None:
            warnings.append(ExportWarning(
                position_id=position_id,
                ordnungszahl=position.ordnungszahl if position else "?",
                reason=f"Artikel {artikel_id} nicht in Datenbank gefunden",
            ))
            continue

        quantity = float(position.quantity or 1)
        unit = position.unit or product.preiseinheit or "Stk"
        unit_price = _resolve_unit_price(product, quantity)

        if unit_price is None:
            unit_price = 0.0
            warnings.append(ExportWarning(
                position_id=position_id,
                ordnungszahl=position.ordnungszahl,
                reason="Kein Preis verfügbar, 0 EUR verwendet",
            ))

        if position.quantity is None:
            warnings.append(ExportWarning(
                position_id=position_id,
                ordnungszahl=position.ordnungszahl,
                reason="Menge nicht erkannt, Standard 1 verwendet",
            ))

        total = round(unit_price * quantity, 2)
        lines.append(
            OfferLine(
                ordnungszahl=position.ordnungszahl,
                description=position.description,
                quantity=quantity,
                unit=unit,
                artikel_id=product.artikel_id,
                artikelname=product.artikelname,
                hersteller=product.hersteller,
                price_net=round(unit_price, 2),
                total_net=total,
            )
        )

    return lines, warnings


@router.post("/export-preview", response_model=ExportPreviewResponse)
def export_preview(request: ExportOfferRequest, db: Session = Depends(get_db)) -> ExportPreviewResponse:
    lines, warnings = _build_offer_lines(request, db)
    total_net = sum(line.total_net for line in lines)
    return ExportPreviewResponse(
        included_count=len(lines),
        total_count=len(request.positions),
        skipped_positions=warnings,
        total_net=round(total_net, 2),
    )


@router.post("/export-offer")
def export_offer(request: ExportOfferRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    lines, _warnings = _build_offer_lines(request, db)

    if not lines:
        raise HTTPException(status_code=400, detail="Keine gültigen Artikel für den Export ausgewählt")

    total_net = sum(line.total_net for line in lines)
    metadata = now_metadata(request.customer_name, request.project_name, total_net, request.customer_address)
    pdf_bytes = build_offer_pdf(lines, metadata)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"tiefbaux-angebot-{timestamp}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/products/search", response_model=list[ProductSearchResult])
def search_products(
    q: str = "",
    category: str | None = None,
    dn: int | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
) -> list[ProductSearchResult]:
    query = select(Product).where(Product.status == "aktiv")

    if q:
        like_q = f"%{q}%"
        query = query.where(
            Product.artikelname.ilike(like_q) | Product.artikelbeschreibung.ilike(like_q)
        )
    if category:
        query = query.where(Product.kategorie == category)
    if dn is not None:
        query = query.where(Product.nennweite_dn == dn)

    query = query.limit(limit)
    products = list(db.scalars(query))

    return [
        ProductSearchResult(
            artikel_id=p.artikel_id,
            artikelname=p.artikelname,
            hersteller=p.hersteller,
            kategorie=p.kategorie,
            nennweite_dn=p.nennweite_dn,
            belastungsklasse=p.belastungsklasse,
            vk_listenpreis_netto=p.vk_listenpreis_netto,
            lager_gesamt=p.lager_gesamt,
            waehrung=p.waehrung,
        )
        for p in products
    ]


@router.post("/compatibility-check", response_model=list[CompatibilityIssue])
def check_compatibility_endpoint(
    request: CompatibilityCheckRequest,
    db: Session = Depends(get_db),
) -> list[CompatibilityIssue]:
    positions_by_id = {p.id: p for p in request.positions}
    selected: list[tuple[LVPosition, ProductSuggestion]] = []

    for pos_id, artikel_id in request.selected_article_ids.items():
        position = positions_by_id.get(pos_id)
        if not position:
            continue
        product = db.scalar(select(Product).where(Product.artikel_id == artikel_id))
        if not product:
            continue
        selected.append((
            position,
            ProductSuggestion(
                artikel_id=product.artikel_id,
                artikelname=product.artikelname,
                category=product.kategorie,
                subcategory=product.unterkategorie,
                dn=product.nennweite_dn,
                load_class=product.belastungsklasse,
                score=0,
            ),
        ))

    return check_compatibility(selected)


def _project_to_summary(p: LVProject) -> ProjectSummary:
    return ProjectSummary(
        id=p.id,
        filename=p.filename,
        project_name=p.project_name,
        total_positions=p.total_positions,
        billable_positions=p.billable_positions,
        service_positions=p.service_positions,
        created_at=p.created_at,
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    projects = db.scalars(
        select(LVProject).order_by(LVProject.created_at.desc())
    ).all()
    return [_project_to_summary(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectDetailResponse:
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    positions = _reconstruct_positions(project.positions)
    return ProjectDetailResponse(project=_project_to_summary(project), positions=positions)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    db.delete(project)
    db.commit()
    return {"ok": True}
