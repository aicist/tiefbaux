from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import LVProject, LVProjectPosition, ManualOverride, Product, Supplier, SupplierInquiry, SupplierOffer, Tender, User
from ..schemas import (
    ComponentSuggestions,
    DuplicateInfo,
    ExportOfferRequest,
    ExportPreviewResponse,
    ExportWarning,
    HealthResponse,
    InquiryBatchCreateRequest,
    InquiryCreateRequest,
    InquiryResponse,
    InquiryStatusUpdate,
    InquiryContentUpdate,
    InquiryCleanupRequest,
    BatchSendRequest,
    BatchSendResponse,
    BundledEmailPreview,
    LVPosition,
    OfferLine,
    OverrideRequest,
    ParseLVResponse,
    PositionSuggestions,
    ProductSearchResult,
    ProductSearchResponse,
    ProductSuggestion,
    ProjectDetailResponse,
    ProjectMetadata,
    ProjectSummary,
    SaveSelectionsRequest,
    SaveWorkstateRequest,
    SupplierCreate,
    SupplierResponse,
    SupplierOfferCreate,
    SupplierOfferResponse,
    SupplierOfferStatusUpdate,
    SuggestionsRequest,
    SuggestionsResponse,
    TechnicalParameters,
    TenderResponse,
    TenderStatusUpdate,
)
import logging

from ..config import settings
from ..services.ai_interpreter import _infer_with_heuristics, enrich_positions_with_parameters
from ..services.llm_parser import _inherit_reference_context, _merge_heuristic_parameters, finalize_position_descriptions, parse_lv_with_llm
from ..services.matcher import _description_hash, load_active_products, suggest_products_for_component, suggest_products_for_position
from ..services.inbound_email_service import get_sync_status as get_inbox_sync_status, sync_inbound_mailbox
from ..services.offer_export import build_offer_pdf, now_metadata
from ..services.pdf_parser import extract_positions_from_pdf

import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _touch_project_editor(project: LVProject, user: User) -> None:
    """Update last_editor on project."""
    project.last_editor_id = user.id
    project.last_edited_at = datetime.utcnow()


router = APIRouter(prefix="/api", tags=["tiefbaux"])

PENDING_INQUIRY_STATUSES = ("offen", "angefragt")


def _display_supplier_email(real_email: str | None) -> str:
    """Mask supplier emails in UI when demo-mail redirect is active."""
    if settings.smtp_demo_mode and settings.smtp_demo_recipients:
        return ", ".join(settings.smtp_demo_recipients)
    return real_email or ""


def _count_pending_project_inquiries(project_id: int, db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(SupplierInquiry)
            .where(SupplierInquiry.project_id == project_id)
            .where(SupplierInquiry.status.in_(PENDING_INQUIRY_STATUSES))
        )
        or 0
    )


def _derive_effective_project_status(project: LVProject, has_pending_inquiries: bool) -> str:
    if has_pending_inquiries:
        return "anfrage_offen"
    if project.offer_pdf_path:
        return "gerechnet"
    return "neu" if (project.status or "neu") == "neu" else "offen"


def _enrich_from_pdf(positions: list[LVPosition], pdf_path: str | None) -> list[LVPosition]:
    """Enrich positions with raw_text and correct source_page from stored PDF."""
    if not pdf_path or not os.path.exists(pdf_path):
        return positions
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        from ..services.llm_parser import (
            _derive_description_from_raw_text,
            _extract_raw_texts_from_pages,
            _map_oz_to_page,
            extract_raw_text_pages,
        )
        pdf_pages = extract_raw_text_pages(pdf_bytes)
        oz_list = [p.ordnungszahl for p in positions]
        raw_texts = _extract_raw_texts_from_pages(pdf_pages, oz_list)
        oz_pages = _map_oz_to_page(pdf_bytes, oz_list)
        return [
            p.model_copy(update={
                **({"raw_text": raw_texts[p.ordnungszahl]} if p.ordnungszahl in raw_texts else {}),
                **({"description": _derive_description_from_raw_text(raw_texts[p.ordnungszahl], p.description)} if p.ordnungszahl in raw_texts else {}),
                **({"source_page": oz_pages[p.ordnungszahl]} if p.ordnungszahl in oz_pages else {}),
            })
            for p in positions
        ]
    except Exception as exc:
        logger.warning("Failed to enrich from PDF: %s", exc)
        return positions


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
    classified: list[LVPosition] = []
    for pos in positions:
        if pos.position_type in ("material", "dienstleistung"):
            classified.append(pos)
            continue
        params = pos.parameters
        inferred_type = "dienstleistung" if params.sortiment_relevant is False else "material"
        classified.append(pos.model_copy(update={
            "position_type": inferred_type,
            "billable": inferred_type == "material",
        }))
    return _upgrade_position_params(classified)


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
            source_page=dbp.source_page,
        ))
    return result


def _upgrade_position_params(positions: list[LVPosition]) -> list[LVPosition]:
    """Fill newly introduced technical fields for already stored projects without reparsing."""
    positions = _inherit_reference_context(positions)
    upgraded: list[LVPosition] = []
    for position in positions:
        inferred = _infer_with_heuristics(position)
        upgraded.append(position.model_copy(update={"parameters": _merge_heuristic_parameters(position, inferred)}))
    return finalize_position_descriptions(upgraded)


def _store_project(
    db: Session,
    content_hash: str,
    filename: str | None,
    positions: list[LVPosition],
    metadata: ProjectMetadata | None = None,
    pdf_path: str | None = None,
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
        pdf_path=pdf_path,
    )
    if metadata:
        project.bauvorhaben = metadata.bauvorhaben
        project.objekt_nr = metadata.objekt_nr
        project.submission_date = metadata.submission_date
        project.auftraggeber = metadata.auftraggeber
        project.kunde_name = metadata.kunde_name
        project.kunde_adresse = metadata.kunde_adresse

    db.add(project)
    db.flush()

    # Generate sequential project number: P-YYMM-NNN
    now = datetime.utcnow()
    prefix = f"P-{now:%y%m}-"
    # Find highest existing number to avoid UNIQUE conflicts
    from sqlalchemy import func as sa_func
    max_nr = db.query(sa_func.max(LVProject.projekt_nr)).filter(
        LVProject.projekt_nr.like(f"{prefix}%")
    ).scalar()
    if max_nr:
        try:
            last_seq = int(max_nr.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    project.projekt_nr = f"{prefix}{last_seq + 1:03d}"

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
            source_page=pos.source_page,
        ))
    db.commit()
    return project


@router.post("/parse-lv", response_model=ParseLVResponse)
async def parse_lv(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ParseLVResponse:
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
        # Enrich raw_text + source_page from stored PDF
        positions = _enrich_from_pdf(positions, existing.pdf_path)
        positions = _upgrade_position_params(positions)
        metadata = ProjectMetadata(
            bauvorhaben=existing.bauvorhaben,
            objekt_nr=existing.objekt_nr,
            submission_date=existing.submission_date,
            auftraggeber=existing.auftraggeber,
            kunde_name=existing.kunde_name,
            kunde_adresse=existing.kunde_adresse,
        )
        # Feature 5: Return stored selections
        selections = None
        if existing.selections_json:
            try:
                selections = json.loads(existing.selections_json)
            except Exception:
                pass
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
            metadata=metadata,
        )

    # New LV — parse normally
    metadata = ProjectMetadata()
    if settings.gemini_api_key:
        try:
            positions, metadata = parse_lv_with_llm(pdf_bytes)
        except Exception as exc:
            logger.warning("LLM parsing failed, falling back to regex: %s", exc)
            positions = _fallback_parse(pdf_bytes)
    else:
        positions = _fallback_parse(pdf_bytes)

    # Feature 8: Store PDF file on disk
    uploads_dir = Path(settings.project_root) / "backend" / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    pdf_filename = f"{content_hash}.pdf"
    pdf_path = str(uploads_dir / pdf_filename)
    try:
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
    except Exception as exc:
        logger.warning("Failed to save PDF: %s", exc)
        pdf_path = None

    # Store for future duplicate detection
    try:
        project = _store_project(db, content_hash, file.filename, positions, metadata, pdf_path)
        _touch_project_editor(project, current_user)
        db.commit()
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
        metadata=metadata,
    )


def _compute_confidence(suggestion: ProductSuggestion, position: LVPosition | None = None) -> str:
    # Check score breakdown for negative critical components
    breakdown_map = {b.component: b.points for b in (suggestion.score_breakdown or [])}
    critical_components = ("DN", "Werkstoff", "Belastungsklasse", "SN-Klasse", "Norm")
    has_negative_critical = any(breakdown_map.get(comp, 0) < 0 for comp in critical_components)

    if has_negative_critical or suggestion.score < 45:
        return "low"

    # Count how many specified critical params matched positively
    if position:
        critical_checks = 0
        critical_passed = 0
        param_map = {
            "DN": position.parameters.nominal_diameter_dn,
            "Werkstoff": position.parameters.material,
            "Belastungsklasse": position.parameters.load_class,
            "SN-Klasse": position.parameters.stiffness_class_sn,
            "Norm": position.parameters.norm,
        }
        for comp_name, param_value in param_map.items():
            if param_value is not None:
                critical_checks += 1
                if breakdown_map.get(comp_name, 0) > 0:
                    critical_passed += 1
        if critical_checks > 0 and critical_passed == critical_checks and suggestion.score > 55:
            return "high"
        if critical_checks > 0 and critical_passed < critical_checks:
            return "low"

    if suggestion.score > 60:
        return "high"
    if suggestion.score >= 45:
        return "medium"
    return "low"


def _offers_by_position(db: Session, project_id: int) -> dict[str, list[SupplierOffer]]:
    """Load all active (non-rejected) supplier offers for a project, grouped by position_id AND ordnungszahl.

    Returns a dict keyed by both position_id and ordnungszahl so that offers
    can be matched even when position IDs change between re-analyses.
    """
    q = (
        select(SupplierOffer)
        .where(SupplierOffer.project_id == project_id)
        .where(SupplierOffer.status != "abgelehnt")
        .order_by(SupplierOffer.created_at.desc())
    )
    offers = db.execute(q).scalars().all()
    by_key: dict[str, list[SupplierOffer]] = {}
    for o in offers:
        if o.position_id:
            by_key.setdefault(str(o.position_id), []).append(o)
        if o.ordnungszahl:
            oz_key = f"oz:{o.ordnungszahl}"
            by_key.setdefault(oz_key, []).append(o)
    return by_key


def _offer_to_suggestion(offer: SupplierOffer, quantity: float | None = None) -> ProductSuggestion:
    """Convert a SupplierOffer to a synthetic ProductSuggestion for the carousel."""
    total = None
    if offer.unit_price is not None and quantity:
        total = round(offer.unit_price * quantity, 2)
    elif offer.total_price is not None:
        total = offer.total_price

    return ProductSuggestion(
        artikel_id=f"SO-{offer.id}",
        artikelname=offer.article_name,
        hersteller=offer.supplier.name if offer.supplier else None,
        price_net=offer.unit_price,
        total_net=total,
        delivery_days=offer.delivery_days,
        score=100.0,
        confidence="high",
        reasons=[f"Lieferantenangebot von {offer.supplier.name}" if offer.supplier else "Lieferantenangebot"],
        warnings=[],
        score_breakdown=[],
        is_supplier_offer=True,
        supplier_offer_id=offer.id,
        supplier_name=offer.supplier.name if offer.supplier else None,
    )


@router.post("/suggestions", response_model=SuggestionsResponse)
def get_suggestions(request: SuggestionsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> SuggestionsResponse:
    products = load_active_products(db)

    # Load supplier offers for this project (if project_id provided)
    offer_map: dict[str, list[SupplierOffer]] = {}
    if request.project_id:
        offer_map = _offers_by_position(db, request.project_id)

    # Phase 1: Score all positions
    scored_pairs: list[tuple[LVPosition, list[ProductSuggestion]]] = []
    for position in request.positions:
        suggestions = suggest_products_for_position(db, position, products=products)
        scored_pairs.append((position, suggestions))

    # Phase 2: Assemble response with confidence (purely score-based)
    position_suggestions: list[PositionSuggestions] = []
    selected_for_check: list[tuple[LVPosition, object]] = []

    for position, final_suggestions in scored_pairs:
        for s in final_suggestions:
            s.confidence = _compute_confidence(s, position)

        # Prepend supplier offers as first suggestions in carousel
        # Try matching by position_id first, then fall back to ordnungszahl
        position_offers = offer_map.get(str(position.id), [])
        if not position_offers and position.ordnungszahl:
            position_offers = offer_map.get(f"oz:{position.ordnungszahl}", [])
        if position_offers:
            offer_suggestions = [_offer_to_suggestion(o, position.quantity) for o in position_offers]
            final_suggestions = offer_suggestions + final_suggestions

        # Multi-component matching with system consistency
        comp_suggestions: list[ComponentSuggestions] | None = None
        if position.parameters.components and len(position.parameters.components) > 1:
            comp_suggestions = []
            dominant_hersteller: str | None = None
            for comp in position.parameters.components:
                comp_results = suggest_products_for_component(db, comp, products, parent_position=position)
                # Enforce system consistency: prefer same manufacturer across components
                if dominant_hersteller and len(comp_results) > 1:
                    same_mfr = [s for s in comp_results if s.hersteller == dominant_hersteller]
                    if same_mfr:
                        comp_results = same_mfr + [s for s in comp_results if s.hersteller != dominant_hersteller]
                # Set dominant manufacturer from first component's top suggestion
                if not dominant_hersteller and comp_results:
                    dominant_hersteller = comp_results[0].hersteller
                for cs in comp_results:
                    cs.confidence = _compute_confidence(cs)
                    if dominant_hersteller and cs.hersteller != dominant_hersteller:
                        cs.warnings = (cs.warnings or []) + [f"Anderer Hersteller als {dominant_hersteller}"]
                comp_suggestions.append(ComponentSuggestions(
                    component_name=comp.component_name,
                    quantity=comp.quantity,
                    suggestions=comp_results,
                ))

        position_suggestions.append(
            PositionSuggestions(
                position_id=position.id,
                ordnungszahl=position.ordnungszahl,
                description=position.description,
                suggestions=final_suggestions,
                component_suggestions=comp_suggestions,
            )
        )
        if final_suggestions:
            selected_for_check.append((position, final_suggestions[0]))

    return SuggestionsResponse(suggestions=position_suggestions)



@router.post("/suggestions/single", response_model=PositionSuggestions)
def get_single_suggestions(position: LVPosition, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> PositionSuggestions:
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
    supplier_offer_text_by_position: dict[str, str] = {}
    if request.project_id:
        offer_rows = db.execute(
            select(SupplierInquiry.position_id, SupplierInquiry.product_description)
            .where(SupplierInquiry.project_id == request.project_id)
            .where(SupplierInquiry.status == "angebot_erhalten")
            .where(SupplierInquiry.position_id.is_not(None))
            .order_by(SupplierInquiry.updated_at.desc())
        ).all()
        for position_id, product_description in offer_rows:
            if not position_id or not product_description:
                continue
            if position_id not in supplier_offer_text_by_position:
                supplier_offer_text_by_position[position_id] = product_description
    lines: list[OfferLine] = []
    warnings: list[ExportWarning] = []

    # Check for material positions without article assignment (skip Dienstleistungen)
    for position in request.positions:
        art_ids = request.selected_article_ids.get(position.id, [])
        if not art_ids and position.position_type != "dienstleistung":
            warnings.append(ExportWarning(
                position_id=position.id,
                ordnungszahl=position.ordnungszahl,
                reason="Kein Artikel zugeordnet",
            ))

    for position_id, artikel_ids in request.selected_article_ids.items():
        position = positions_by_id.get(position_id)
        if position is None:
            continue
        assignment_keys = request.assignment_keys_by_position.get(position_id, [])

        for art_idx, artikel_id in enumerate(artikel_ids):
            is_additional = art_idx > 0
            assignment_key = assignment_keys[art_idx] if art_idx < len(assignment_keys) else f"{position_id}::{art_idx}"

            # Handle supplier offer articles (SO-{id})
            if artikel_id.startswith("SO-"):
                offer_id = int(artikel_id[3:])
                offer = db.get(SupplierOffer, offer_id)
                if offer is None:
                    warnings.append(ExportWarning(
                        position_id=position_id,
                        ordnungszahl=position.ordnungszahl if position else "?",
                        reason=f"Lieferantenangebot {artikel_id} nicht gefunden",
                    ))
                    continue
                quantity = float(position.quantity or 1)
                unit = position.unit or offer.unit or "Stk"
                unit_price = offer.unit_price or 0.0
                custom_unit_price = request.custom_unit_prices.get(assignment_key)
                if custom_unit_price is not None:
                    unit_price = max(unit_price, custom_unit_price)
                total = round(unit_price * quantity, 2)
                supplier_name = offer.supplier.name if offer.supplier else "Lieferant"
                lines.append(
                    OfferLine(
                        ordnungszahl=position.ordnungszahl,
                        description=supplier_offer_text_by_position.get(position_id, position.description),
                        quantity=quantity,
                        unit=unit,
                        artikel_id=offer.article_number or artikel_id,
                        artikelname=offer.article_name,
                        hersteller=supplier_name,
                        price_net=round(unit_price, 2),
                        total_net=total,
                        is_additional=is_additional,
                        is_alternative=request.alternative_flags.get(assignment_key, False),
                        supplier_open=request.supplier_open_flags.get(assignment_key, False),
                    )
                )
                grand_total += total
                included_count += 1
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
                    reason=f"Kein Preis verfügbar für {artikel_id}, 0 EUR verwendet",
                ))

            # Custom unit prices only apply to primary article
            custom_unit_price = request.custom_unit_prices.get(assignment_key)
            if custom_unit_price is not None:
                if custom_unit_price < unit_price:
                    warnings.append(ExportWarning(
                        position_id=position_id,
                        ordnungszahl=position.ordnungszahl,
                        reason="VK unter EK nicht erlaubt, EK verwendet",
                    ))
                unit_price = max(unit_price, custom_unit_price)

            if not is_additional:
                if custom_unit_price is not None:
                    pass
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
                    description=supplier_offer_text_by_position.get(position_id, position.description),
                    quantity=quantity,
                    unit=unit,
                    artikel_id=product.artikel_id,
                    artikelname=product.artikelname,
                    hersteller=product.hersteller,
                    price_net=round(unit_price, 2),
                    total_net=total,
                    is_additional=is_additional,
                    is_alternative=request.alternative_flags.get(assignment_key, False),
                    supplier_open=request.supplier_open_flags.get(assignment_key, False),
                )
            )

    return lines, warnings


def _validate_offer_export_requirements(request: ExportOfferRequest, db: Session) -> None:
    # Angebot darf erst erstellt werden, wenn alle offenen Lieferantenanfragen geklärt sind.
    if request.project_id:
        pending_inquiries = _count_pending_project_inquiries(request.project_id, db)
        if pending_inquiries > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Angebot gesperrt: {pending_inquiries} offene Lieferantenanfrage(n) vorhanden.",
            )

    selected_by_position = request.selected_article_ids or {}
    assignment_keys_by_position = request.assignment_keys_by_position or {}

    for position in request.positions:
        if not position.billable or position.position_type == "dienstleistung":
            continue

        selected_ids = selected_by_position.get(position.id, [])
        if not selected_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Angebot gesperrt: Position {position.ordnungszahl} ist noch nicht zugeordnet.",
            )

        assignment_keys = assignment_keys_by_position.get(position.id, [])
        if assignment_keys and len(assignment_keys) != len(selected_ids):
            raise HTTPException(
                status_code=400,
                detail=f"Angebot gesperrt: Zuordnungsdaten für Position {position.ordnungszahl} sind unvollständig.",
            )

        required_components = position.parameters.components or []
        if required_components:
            required_component_keys = {
                f"{position.id}::component::{component.component_name}" for component in required_components
            }
            missing_component_keys = [key for key in required_component_keys if key not in assignment_keys]
            if missing_component_keys:
                raise HTTPException(
                    status_code=400,
                    detail=f"Angebot gesperrt: Komponenten für Position {position.ordnungszahl} sind nicht vollständig zugeordnet.",
                )


@router.post("/export-preview", response_model=ExportPreviewResponse)
def export_preview(request: ExportOfferRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ExportPreviewResponse:
    _validate_offer_export_requirements(request, db)
    lines, warnings = _build_offer_lines(request, db)
    total_net = sum(line.total_net for line in lines)
    return ExportPreviewResponse(
        included_count=len(lines),
        total_count=len(request.positions),
        skipped_positions=warnings,
        total_net=round(total_net, 2),
    )


@router.post("/export-offer")
def export_offer(request: ExportOfferRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> StreamingResponse:
    _validate_offer_export_requirements(request, db)
    lines, _warnings = _build_offer_lines(request, db)

    if not lines:
        raise HTTPException(status_code=400, detail="Keine gültigen Artikel für den Export ausgewählt")

    total_net = sum(line.total_net for line in lines)
    metadata = now_metadata(request.customer_name, request.project_name, total_net, request.customer_address)
    pdf_bytes = build_offer_pdf(lines, metadata)

    # Save offer PDF to disk and update project status
    if request.project_id:
        project = db.get(LVProject, request.project_id)
        if project:
            offers_dir = Path(settings.project_root) / "backend" / "offers" / str(request.project_id)
            offers_dir.mkdir(parents=True, exist_ok=True)
            offer_path = offers_dir / "angebot.pdf"
            offer_path.write_bytes(pdf_bytes)
            project.offer_pdf_path = str(offer_path)
            project.status = "gerechnet"
            _touch_project_editor(project, current_user)
            db.commit()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"tiefbaux-angebot-{timestamp}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/products/search", response_model=ProductSearchResponse)
def search_products(
    q: str = "",
    category: str | None = None,
    dn: int | None = None,
    sn: str | None = None,
    load_class: str | None = None,
    material: str | None = None,
    angle: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductSearchResponse:
    query = select(Product)

    if q:
        like_q = f"%{q}%"
        query = query.where(
            Product.artikel_id.ilike(like_q)
            | Product.artikelname.ilike(like_q)
            | Product.artikelbeschreibung.ilike(like_q)
        )
    if category:
        query = query.where(Product.kategorie == category)
    if dn is not None:
        query = query.where(Product.nennweite_dn == dn)
    if sn is not None:
        query = query.where(Product.steifigkeitsklasse_sn == sn)
    if load_class is not None:
        query = query.where(Product.belastungsklasse.ilike(f"%{load_class}%"))
    if material is not None:
        query = query.where(Product.werkstoff.ilike(f"%{material}%"))
    if angle is not None:
        query = query.where(Product.artikelname.ilike(f"%{angle}°%"))

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    query = query.order_by(Product.artikelname.asc(), Product.artikel_id.asc()).offset(safe_offset).limit(safe_limit + 1)
    products = list(db.scalars(query))
    has_more = len(products) > safe_limit
    products = products[:safe_limit]

    return ProductSearchResponse(
        items=[
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
                steifigkeitsklasse_sn=p.steifigkeitsklasse_sn,
                norm_primaer=p.norm_primaer,
                werkstoff=p.werkstoff,
            )
            for p in products
        ],
        has_more=has_more,
    )


def _project_to_summary(p: LVProject, has_pending_inquiries: bool = False) -> ProjectSummary:
    effective_status = _derive_effective_project_status(p, has_pending_inquiries)
    return ProjectSummary(
        id=p.id,
        filename=p.filename,
        project_name=p.project_name,
        projekt_nr=p.projekt_nr,
        total_positions=p.total_positions,
        billable_positions=p.billable_positions,
        service_positions=p.service_positions,
        created_at=p.created_at,
        bauvorhaben=p.bauvorhaben,
        objekt_nr=p.objekt_nr,
        submission_date=p.submission_date,
        kunde_name=p.kunde_name,
        status=effective_status,
        offer_pdf_path=p.offer_pdf_path,
        assigned_user_name=p.assigned_user.name if p.assigned_user else None,
        last_editor_name=p.last_editor.name if p.last_editor else None,
        last_edited_at=p.last_edited_at,
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(q: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ProjectSummary]:
    query = select(LVProject).order_by(LVProject.created_at.desc())
    if q:
        like_q = f"%{q}%"
        query = query.where(
            LVProject.filename.ilike(like_q)
            | LVProject.bauvorhaben.ilike(like_q)
            | LVProject.kunde_name.ilike(like_q)
            | LVProject.objekt_nr.ilike(like_q)
            | LVProject.project_name.ilike(like_q)
        )
    projects = db.scalars(query).all()
    project_ids = [p.id for p in projects]
    pending_map: dict[int, int] = {}
    if project_ids:
        pending_rows = db.execute(
            select(SupplierInquiry.project_id, func.count())
            .where(SupplierInquiry.project_id.in_(project_ids))
            .where(SupplierInquiry.status.in_(PENDING_INQUIRY_STATUSES))
            .group_by(SupplierInquiry.project_id)
        ).all()
        pending_map = {int(project_id): int(count) for project_id, count in pending_rows if project_id is not None}

    return [_project_to_summary(p, has_pending_inquiries=pending_map.get(p.id, 0) > 0) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> ProjectDetailResponse:
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    has_pending_inquiries = _count_pending_project_inquiries(project.id, db) > 0
    # Transition: neu → offen when first loaded (only when no blocking pending inquiries exist).
    if (project.status or "neu") == "neu" and not has_pending_inquiries:
        project.status = "offen"
    effective_status = _derive_effective_project_status(project, has_pending_inquiries)
    if project.status != effective_status:
        project.status = effective_status
    db.commit()
    positions = _reconstruct_positions(project.positions)
    positions = _enrich_from_pdf(positions, project.pdf_path)
    positions = _upgrade_position_params(positions)
    metadata = ProjectMetadata(
        bauvorhaben=project.bauvorhaben,
        objekt_nr=project.objekt_nr,
        submission_date=project.submission_date,
        auftraggeber=project.auftraggeber,
        kunde_name=project.kunde_name,
        kunde_adresse=project.kunde_adresse,
    )
    selections = None
    decisions = None
    component_selections = None
    ui_state = None
    if project.selections_json:
        try:
            selections = json.loads(project.selections_json)
        except Exception:
            pass
    if project.workstate_json:
        try:
            workstate = json.loads(project.workstate_json)
            if isinstance(workstate, dict):
                ws_selections = workstate.get("selected_article_ids")
                ws_decisions = workstate.get("decisions")
                ws_component_selections = workstate.get("component_selections")
                ws_ui_state = workstate.get("ui_state")
                if isinstance(ws_selections, dict):
                    selections = ws_selections
                if isinstance(ws_decisions, dict):
                    decisions = ws_decisions
                if isinstance(ws_component_selections, dict):
                    component_selections = ws_component_selections
                if isinstance(ws_ui_state, dict):
                    ui_state = ws_ui_state
        except Exception:
            pass
    return ProjectDetailResponse(
        project=_project_to_summary(project, has_pending_inquiries=has_pending_inquiries),
        positions=positions,
        metadata=metadata,
        selections=selections,
        decisions=decisions,
        component_selections=component_selections,
        ui_state=ui_state,
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/projects/save-selections")
def save_selections(request: SaveSelectionsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Feature 5: Save article selections for a project (for duplicate reuse)."""
    project = db.get(LVProject, request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    project.selections_json = json.dumps(request.selected_article_ids)
    try:
        current_workstate = json.loads(project.workstate_json) if project.workstate_json else {}
    except Exception:
        current_workstate = {}
    if not isinstance(current_workstate, dict):
        current_workstate = {}
    current_workstate["selected_article_ids"] = request.selected_article_ids
    project.workstate_json = json.dumps(current_workstate)
    _touch_project_editor(project, current_user)
    db.commit()
    return {"ok": True}


@router.post("/projects/save-workstate")
def save_workstate(request: SaveWorkstateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(LVProject, request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

    project.selections_json = json.dumps(request.selected_article_ids)
    project.workstate_json = json.dumps({
        "selected_article_ids": request.selected_article_ids,
        "decisions": request.decisions,
        "component_selections": request.component_selections,
        "ui_state": request.ui_state.model_dump() if request.ui_state else None,
    })
    _touch_project_editor(project, current_user)
    db.commit()
    return {"ok": True}


@router.post("/overrides")
def record_override(request: OverrideRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Feature 6: Record a manual product selection for learning."""
    desc_hash = _description_hash(request.position_description)
    existing = db.scalar(
        select(ManualOverride).where(
            ManualOverride.description_hash == desc_hash,
            ManualOverride.chosen_artikel_id == request.chosen_artikel_id,
        )
    )
    if existing:
        existing.override_count += 1
        existing.updated_at = datetime.now()
    else:
        db.add(ManualOverride(
            description_hash=desc_hash,
            ordnungszahl_pattern=request.ordnungszahl,
            category=request.category,
            dn=request.dn,
            material=request.material,
            chosen_artikel_id=request.chosen_artikel_id,
        ))
    db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/pdf")
def get_project_pdf(project_id: int, token: str | None = None, db: Session = Depends(get_db)):
    """Feature 8: Serve the stored PDF file for a project."""
    from ..auth import _resolve_user_from_token
    _resolve_user_from_token(token, db)
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if not project.pdf_path or not os.path.exists(project.pdf_path):
        raise HTTPException(status_code=404, detail="PDF nicht verfügbar")

    def _iter_file():
        with open(project.pdf_path, "rb") as f:
            yield f.read()

    return StreamingResponse(
        _iter_file(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{project.filename or "lv.pdf"}"'},
    )


@router.get("/projects/{project_id}/offer-pdf")
def get_project_offer_pdf(project_id: int, token: str | None = None, db: Session = Depends(get_db)):
    """Serve the stored offer PDF for a project."""
    from ..auth import _resolve_user_from_token
    _resolve_user_from_token(token, db)
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    if not project.offer_pdf_path or not os.path.exists(project.offer_pdf_path):
        raise HTTPException(status_code=404, detail="Angebots-PDF nicht verfügbar")

    def _iter_file():
        with open(project.offer_pdf_path, "rb") as f:
            yield f.read()

    return StreamingResponse(
        _iter_file(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="angebot-{project.projekt_nr or project.id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Supplier & Inquiry endpoints
# ---------------------------------------------------------------------------


def _supplier_to_response(s: Supplier) -> SupplierResponse:
    import json as _json
    cats: list[str] = []
    if s.categories_json:
        try:
            cats = _json.loads(s.categories_json)
        except Exception:
            cats = []
    return SupplierResponse(
        id=s.id, name=s.name, email=_display_supplier_email(s.email), phone=s.phone,
        categories=cats, notes=s.notes, active=s.active,
    )


@router.get("/suppliers", response_model=list[SupplierResponse])
def list_suppliers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    suppliers = db.execute(
        select(Supplier).where(Supplier.active == True).order_by(Supplier.name)
    ).scalars().all()
    return [_supplier_to_response(s) for s in suppliers]


@router.post("/suppliers", response_model=SupplierResponse)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s = Supplier(
        name=data.name, email=data.email, phone=data.phone,
        categories_json=json.dumps(data.categories) if data.categories else None,
        notes=data.notes,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _supplier_to_response(s)


@router.put("/suppliers/{supplier_id}", response_model=SupplierResponse)
def update_supplier(supplier_id: int, data: SupplierCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Lieferant nicht gefunden")
    s.name = data.name
    s.email = data.email
    s.phone = data.phone
    s.categories_json = json.dumps(data.categories) if data.categories else None
    s.notes = data.notes
    db.commit()
    db.refresh(s)
    return _supplier_to_response(s)


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Lieferant nicht gefunden")
    s.active = False
    db.commit()
    return {"ok": True}


@router.post("/inquiries", response_model=InquiryResponse)
def create_inquiry(data: InquiryCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from ..services.email_service import build_inquiry_email, send_email

    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Lieferant nicht gefunden")

    # Check for existing open inquiry for same position + supplier + project
    if data.position_id:
        q = (
            select(SupplierInquiry)
            .where(SupplierInquiry.position_id == data.position_id)
            .where(SupplierInquiry.supplier_id == data.supplier_id)
            .where(SupplierInquiry.status == "offen")
        )
        if data.project_id:
            q = q.where(SupplierInquiry.project_id == data.project_id)
        else:
            q = q.where(SupplierInquiry.project_id.is_(None))
        existing = db.execute(q).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Für diese Position und diesen Lieferanten existiert bereits eine offene Anfrage",
            )

    # Get project name for email
    project_name = None
    if data.project_id:
        project = db.get(LVProject, data.project_id)
        if project:
            project_name = project.bauvorhaben or project.project_name

    params_dict = data.technical_params.model_dump(exclude_none=True) if data.technical_params else None
    reference_lines = [
        f"TBX-PROJ:{data.project_id or 0}|OZ:{data.ordnungszahl or '-'}|SUP:{supplier.id}"
    ]

    subject, body = build_inquiry_email(
        product_description=data.product_description,
        project_name=project_name,
        technical_params=params_dict,
        quantity=data.quantity,
        unit=data.unit,
        custom_message=data.custom_message,
        reference_lines=reference_lines,
    )

    status = "offen"
    sent_at = None
    if data.send_email:
        sent = send_email(supplier.email, subject, body)
        status = "angefragt"
        if sent:
            sent_at = datetime.utcnow()

    inquiry = SupplierInquiry(
        supplier_id=supplier.id,
        project_id=data.project_id,
        position_id=data.position_id,
        ordnungszahl=data.ordnungszahl,
        product_description=data.product_description,
        technical_params_json=json.dumps(params_dict) if params_dict else None,
        quantity=data.quantity,
        unit=data.unit,
        status=status,
        sent_at=sent_at,
        email_subject=subject,
        email_body=body,
    )
    db.add(inquiry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Für diese Position und diesen Lieferanten existiert bereits eine offene Anfrage",
        )
    db.refresh(inquiry)

    return InquiryResponse(
        id=inquiry.id,
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        supplier_email=_display_supplier_email(supplier.email),
        project_id=inquiry.project_id,
        position_id=inquiry.position_id,
        ordnungszahl=inquiry.ordnungszahl,
        product_description=inquiry.product_description,
        quantity=inquiry.quantity,
        unit=inquiry.unit,
        status=inquiry.status,
        sent_at=inquiry.sent_at,
        email_subject=inquiry.email_subject,
        email_body=inquiry.email_body,
        notes=inquiry.notes,
        created_at=inquiry.created_at,
    )


@router.get("/inquiries", response_model=list[InquiryResponse])
def list_inquiries(
    project_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(SupplierInquiry).join(Supplier)
    if project_id is not None:
        q = q.where(SupplierInquiry.project_id == project_id)
    if status:
        q = q.where(SupplierInquiry.status == status)
    q = q.order_by(SupplierInquiry.created_at.desc())

    inquiries = db.execute(q).scalars().all()
    result = []
    for inq in inquiries:
        supplier = db.get(Supplier, inq.supplier_id)
        result.append(InquiryResponse(
            id=inq.id,
            supplier_id=supplier.id if supplier else 0,
            supplier_name=supplier.name if supplier else "?",
            supplier_email=_display_supplier_email(supplier.email if supplier else ""),
            project_id=inq.project_id,
            position_id=inq.position_id,
            ordnungszahl=inq.ordnungszahl,
            product_description=inq.product_description,
            quantity=inq.quantity,
            unit=inq.unit,
            status=inq.status,
            sent_at=inq.sent_at,
            email_subject=inq.email_subject,
            email_body=inq.email_body,
            notes=inq.notes,
            created_at=inq.created_at,
        ))
    return result


@router.post("/inquiries/cleanup-open")
def cleanup_open_inquiries_for_position(
    data: InquiryCleanupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete draft inquiries (status=offen) for one project position."""
    open_inquiries = db.execute(
        select(SupplierInquiry)
        .where(SupplierInquiry.project_id == data.project_id)
        .where(SupplierInquiry.position_id == data.position_id)
        .where(SupplierInquiry.status == "offen")
    ).scalars().all()

    deleted_count = len(open_inquiries)
    for inquiry in open_inquiries:
        db.delete(inquiry)

    project = db.get(LVProject, data.project_id)
    if project and deleted_count > 0:
        has_pending_inquiries = _count_pending_project_inquiries(project.id, db) > 0
        project.status = _derive_effective_project_status(project, has_pending_inquiries)
        _touch_project_editor(project, current_user)

    db.commit()
    return {"ok": True, "deleted_count": deleted_count}


@router.patch("/inquiries/{inquiry_id}/status")
def update_inquiry_status(
    inquiry_id: int,
    data: InquiryStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inq = db.get(SupplierInquiry, inquiry_id)
    if not inq:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden")
    if data.status not in ("offen", "angefragt", "angebot_erhalten"):
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    inq.status = data.status
    if data.notes is not None:
        inq.notes = data.notes
    if inq.project_id:
        project = db.get(LVProject, inq.project_id)
        if project:
            has_pending_inquiries = _count_pending_project_inquiries(project.id, db) > 0
            project.status = _derive_effective_project_status(project, has_pending_inquiries)
            _touch_project_editor(project, current_user)
    db.commit()
    return {"ok": True}


@router.patch("/inquiries/{inquiry_id}/content")
def update_inquiry_content(
    inquiry_id: int,
    data: InquiryContentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inq = db.get(SupplierInquiry, inquiry_id)
    if not inq:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden")
    if data.email_subject is not None:
        inq.email_subject = data.email_subject
    if data.email_body is not None:
        inq.email_body = data.email_body
    if data.product_description is not None:
        inq.product_description = data.product_description
    db.commit()
    return {"ok": True}


@router.post("/inquiries/batch", response_model=list[InquiryResponse])
def create_inquiry_batch(data: InquiryBatchCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create inquiries for multiple suppliers at once (without sending emails)."""
    from ..services.email_service import build_inquiry_email

    project_name = None
    if data.project_id:
        project = db.get(LVProject, data.project_id)
        if project:
            project_name = project.bauvorhaben or project.project_name

    params_dict = data.technical_params.model_dump(exclude_none=True) if data.technical_params else None
    reference_lines = [f"TBX-PROJ:{data.project_id or 0}|OZ:{data.ordnungszahl or '-'}"]
    subject, body = build_inquiry_email(
        product_description=data.product_description,
        project_name=project_name,
        technical_params=params_dict,
        quantity=data.quantity,
        unit=data.unit,
        custom_message=data.custom_message,
        reference_lines=reference_lines,
    )

    # Find existing open inquiries for this position to prevent duplicates
    existing_supplier_ids: set[int] = set()
    if data.position_id:
        q = (
            select(SupplierInquiry.supplier_id)
            .where(SupplierInquiry.position_id == data.position_id)
            .where(SupplierInquiry.status == "offen")
        )
        if data.project_id:
            q = q.where(SupplierInquiry.project_id == data.project_id)
        else:
            q = q.where(SupplierInquiry.project_id.is_(None))
        existing_supplier_ids = set(db.execute(q).scalars().all())

    results = []
    for supplier_id in data.supplier_ids:
        # Skip if an open inquiry already exists for this position + supplier
        if supplier_id in existing_supplier_ids:
            continue
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            continue
        inquiry = SupplierInquiry(
            supplier_id=supplier.id,
            project_id=data.project_id,
            position_id=data.position_id,
            ordnungszahl=data.ordnungszahl,
            product_description=data.product_description,
            technical_params_json=json.dumps(params_dict) if params_dict else None,
            quantity=data.quantity,
            unit=data.unit,
            status="offen",
            email_subject=subject,
            email_body=body,
        )
        db.add(inquiry)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        results.append(InquiryResponse(
            id=inquiry.id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_email=_display_supplier_email(supplier.email),
            project_id=inquiry.project_id,
            position_id=inquiry.position_id,
            ordnungszahl=inquiry.ordnungszahl,
            product_description=inquiry.product_description,
            quantity=inquiry.quantity,
            unit=inquiry.unit,
            status=inquiry.status,
            sent_at=None,
            email_subject=inquiry.email_subject,
            email_body=inquiry.email_body,
            notes=inquiry.notes,
            created_at=inquiry.created_at,
        ))
    db.commit()
    return results


def _build_supplier_bundles(
    project_id: int, db: Session
) -> tuple[str | None, dict[int, list[SupplierInquiry]]]:
    """Helper: load open inquiries for project and group by supplier."""
    inquiries = db.execute(
        select(SupplierInquiry)
        .where(SupplierInquiry.project_id == project_id)
        .where(SupplierInquiry.status == "offen")
    ).scalars().all()

    project_name = None
    project = db.get(LVProject, project_id)
    if project:
        project_name = project.bauvorhaben or project.project_name

    by_supplier: dict[int, list[SupplierInquiry]] = {}
    for inq in inquiries:
        by_supplier.setdefault(inq.supplier_id, []).append(inq)

    return project_name, by_supplier


@router.post("/inquiries/preview-bundled", response_model=list[BundledEmailPreview])
def preview_bundled_inquiries(data: BatchSendRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Generate bundled email previews per supplier (without sending)."""
    from ..services.email_service import build_bundled_inquiry_email

    project_name, by_supplier = _build_supplier_bundles(data.project_id, db)
    previews = []

    for supplier_id, supplier_inquiries in by_supplier.items():
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            continue

        items = []
        for inq in supplier_inquiries:
            params = json.loads(inq.technical_params_json) if inq.technical_params_json else None
            items.append({
                "product_description": inq.product_description,
                "technical_params": params,
                "quantity": inq.quantity,
                "unit": inq.unit,
                "ordnungszahl": inq.ordnungszahl,
                "reference_code": f"TBX-INQ:{inq.id}|PROJ:{inq.project_id or 0}|OZ:{inq.ordnungszahl or '-'}",
            })

        subject, body = build_bundled_inquiry_email(
            items=items,
            project_name=project_name,
        )

        previews.append(BundledEmailPreview(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_email=_display_supplier_email(supplier.email),
            subject=subject,
            body=body,
            inquiry_ids=[inq.id for inq in supplier_inquiries],
            positions=[
                {
                    "ordnungszahl": inq.ordnungszahl,
                    "product_description": inq.product_description,
                    "quantity": inq.quantity,
                    "unit": inq.unit,
                }
                for inq in supplier_inquiries
            ],
        ))

    return previews


@router.post("/inquiries/send-batch", response_model=BatchSendResponse)
def send_batch_inquiries(data: BatchSendRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Send bundled emails per supplier for all open inquiries of a project.

    Accepts optional email_overrides: {supplier_id: {subject, body}} for
    user-edited email content.
    If simulate_only is true, no real email is sent.
    """
    from ..services.email_service import build_bundled_inquiry_email, send_email as do_send

    project_name, by_supplier = _build_supplier_bundles(data.project_id, db)

    sent_count = 0
    failed_count = 0

    for supplier_id, supplier_inquiries in by_supplier.items():
        supplier = db.get(Supplier, supplier_id)
        if not supplier:
            failed_count += len(supplier_inquiries)
            continue

        # Check for user overrides first
        override = data.email_overrides.get(supplier_id)
        if override and "subject" in override and "body" in override:
            subject = override["subject"]
            body = override["body"]
            if "TBX-INQ" not in body:
                reference_lines = [
                    f"[TBX-INQ:{inq.id}|PROJ:{inq.project_id or 0}|OZ:{inq.ordnungszahl or '-'}]"
                    for inq in supplier_inquiries
                ]
                body = (
                    f"{body.rstrip()}\n\n"
                    "Bitte diese Referenzzeilen in der Antwort belassen (für automatische Zuordnung):\n"
                    f"{chr(10).join(reference_lines)}"
                )
        else:
            # Build bundled email from inquiry data
            items = []
            for inq in supplier_inquiries:
                params = json.loads(inq.technical_params_json) if inq.technical_params_json else None
                items.append({
                    "product_description": inq.product_description,
                    "technical_params": params,
                    "quantity": inq.quantity,
                    "unit": inq.unit,
                    "ordnungszahl": inq.ordnungszahl,
                    "reference_code": f"TBX-INQ:{inq.id}|PROJ:{inq.project_id or 0}|OZ:{inq.ordnungszahl or '-'}",
                })
            subject, body = build_bundled_inquiry_email(
                items=items,
                project_name=project_name,
            )

        if data.simulate_only:
            success = True
        else:
            success = do_send(supplier.email, subject, body)
        now = datetime.utcnow()
        for inq in supplier_inquiries:
            if success:
                inq.status = "angefragt"
                inq.sent_at = now
                inq.email_subject = subject
                inq.email_body = body
                sent_count += 1
            else:
                failed_count += 1

    db.commit()
    return BatchSendResponse(sent_count=sent_count, failed_count=failed_count)


@router.post("/inbox/sync-demo")
def sync_demo_inbox(
    max_messages: int = 20,
    mark_seen: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_limit = max(1, min(max_messages, 100))
    return sync_inbound_mailbox(db, max_messages=safe_limit, force_mark_seen=mark_seen)


@router.get("/inbox/sync-status")
def inbox_sync_status(current_user: User = Depends(get_current_user)):
    return get_inbox_sync_status()


# ──────────────────────────────────────────────────────────────
#  Lieferantenangebote (Supplier Offers)
# ──────────────────────────────────────────────────────────────

def _offer_to_response(offer: SupplierOffer) -> SupplierOfferResponse:
    return SupplierOfferResponse(
        id=offer.id,
        inquiry_id=offer.inquiry_id,
        supplier_id=offer.supplier_id,
        supplier_name=offer.supplier.name if offer.supplier else "Unbekannt",
        project_id=offer.project_id,
        position_id=offer.position_id,
        ordnungszahl=offer.ordnungszahl,
        article_name=offer.article_name,
        article_number=offer.article_number,
        unit_price=offer.unit_price,
        total_price=offer.total_price,
        delivery_days=offer.delivery_days,
        quantity=offer.quantity,
        unit=offer.unit,
        notes=offer.notes,
        source=offer.source,
        status=offer.status,
        created_at=offer.created_at,
    )


@router.post("/offers", response_model=SupplierOfferResponse)
def create_offer(
    req: SupplierOfferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    supplier = db.get(Supplier, req.supplier_id)
    if not supplier:
        raise HTTPException(404, "Lieferant nicht gefunden")

    offer = SupplierOffer(
        inquiry_id=req.inquiry_id,
        supplier_id=req.supplier_id,
        project_id=req.project_id,
        position_id=req.position_id,
        ordnungszahl=req.ordnungszahl,
        article_name=req.article_name,
        article_number=req.article_number,
        unit_price=req.unit_price,
        total_price=req.total_price,
        delivery_days=req.delivery_days,
        quantity=req.quantity,
        unit=req.unit,
        notes=req.notes,
        source=req.source,
    )
    db.add(offer)

    # If linked to an inquiry, update inquiry status
    if req.inquiry_id:
        inquiry = db.get(SupplierInquiry, req.inquiry_id)
        if inquiry:
            inquiry.status = "angebot_erhalten"
            inquiry.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(offer)
    return _offer_to_response(offer)


@router.get("/offers", response_model=list[SupplierOfferResponse])
def list_offers(
    project_id: int | None = None,
    position_id: str | None = None,
    supplier_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(SupplierOffer)
    if project_id is not None:
        q = q.where(SupplierOffer.project_id == project_id)
    if position_id is not None:
        q = q.where(SupplierOffer.position_id == position_id)
    if supplier_id is not None:
        q = q.where(SupplierOffer.supplier_id == supplier_id)
    if status is not None:
        q = q.where(SupplierOffer.status == status)
    q = q.order_by(SupplierOffer.created_at.desc())
    offers = db.execute(q).scalars().all()
    return [_offer_to_response(o) for o in offers]


@router.patch("/offers/{offer_id}/status", response_model=SupplierOfferResponse)
def update_offer_status(
    offer_id: int,
    req: SupplierOfferStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offer = db.get(SupplierOffer, offer_id)
    if not offer:
        raise HTTPException(404, "Angebot nicht gefunden")
    offer.status = req.status
    offer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(offer)
    return _offer_to_response(offer)


@router.delete("/offers/{offer_id}")
def delete_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offer = db.get(SupplierOffer, offer_id)
    if not offer:
        raise HTTPException(404, "Angebot nicht gefunden")
    db.delete(offer)
    db.commit()
    return {"ok": True}


# ──────────────────────────────────────────────────────────────
#  Objektradar — Ausschreibungen
# ──────────────────────────────────────────────────────────────

@router.get("/tenders", response_model=list[TenderResponse])
def list_tenders(
    status: str | None = None,
    min_relevance: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alle gefundenen Ausschreibungen (optional nach Status/Relevanz filtern)."""
    q = db.query(Tender)
    if status:
        q = q.filter(Tender.status == status)
    if min_relevance > 0:
        q = q.filter(Tender.relevance_score >= min_relevance)
    q = q.order_by(Tender.relevance_score.desc(), Tender.created_at.desc())
    tenders = q.all()

    result = []
    for t in tenders:
        cpv = []
        if t.cpv_codes:
            try:
                cpv = json.loads(t.cpv_codes)
            except (json.JSONDecodeError, TypeError):
                cpv = []
        result.append(TenderResponse(
            id=t.id,
            external_id=t.external_id,
            title=t.title,
            description=t.description,
            auftraggeber=t.auftraggeber,
            ort=t.ort,
            cpv_codes=cpv,
            submission_deadline=t.submission_deadline,
            publication_date=t.publication_date,
            url=t.url,
            status=t.status,
            relevance_score=t.relevance_score,
            lat=t.lat,
            lng=t.lng,
            created_at=t.created_at,
            project_id=t.project_id,
        ))
    return result


@router.post("/tenders/refresh")
def refresh_tenders_endpoint(current_user: User = Depends(get_current_user)):
    """Manueller Trigger: Neue Ausschreibungen im Hintergrund abrufen."""
    from ..services.tender_crawler import refresh_tenders_background, get_refresh_status
    from ..database import SessionLocal
    status = get_refresh_status()
    if status["running"]:
        return {"status": "already_running"}
    refresh_tenders_background(SessionLocal)
    return {"status": "started"}


@router.get("/tenders/refresh-status")
def refresh_status_endpoint(current_user: User = Depends(get_current_user)):
    """Status des laufenden Refreshs abfragen."""
    from ..services.tender_crawler import get_refresh_status
    return get_refresh_status()


@router.patch("/tenders/{tender_id}")
def update_tender_status(
    tender_id: int,
    data: TenderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Status einer Ausschreibung ändern (neu/relevant/irrelevant/analysiert)."""
    tender = db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail="Ausschreibung nicht gefunden")
    if data.status not in ("neu", "relevant", "irrelevant", "analysiert"):
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    tender.status = data.status
    db.commit()
    return {"ok": True}
