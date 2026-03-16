from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LVProject, LVProjectPosition, ManualOverride, Product, Supplier, SupplierInquiry
from ..schemas import (
    CompatibilityCheckRequest,
    CompatibilityIssue,
    DuplicateInfo,
    ExportOfferRequest,
    ExportPreviewResponse,
    ExportWarning,
    HealthResponse,
    InquiryCreateRequest,
    InquiryResponse,
    InquiryStatusUpdate,
    LVPosition,
    OfferLine,
    OverrideRequest,
    ParseLVResponse,
    PositionSuggestions,
    ProductSearchResult,
    ProductSuggestion,
    ProjectDetailResponse,
    ProjectMetadata,
    ProjectSummary,
    SaveSelectionsRequest,
    SupplierCreate,
    SupplierResponse,
    SuggestionsRequest,
    SuggestionsResponse,
    TechnicalParameters,
)
import logging

from ..config import settings
from ..services.ai_interpreter import enrich_positions_with_parameters
from ..services.compatibility import check_compatibility
from ..services.llm_parser import parse_lv_with_llm
from ..services.matcher import _description_hash, load_active_products, suggest_products_for_position
from ..services.offer_export import build_offer_pdf, now_metadata
from ..services.pdf_parser import extract_positions_from_pdf

import os
from pathlib import Path

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
            source_page=dbp.source_page,
        ))
    return result


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


def _compute_confidence(suggestion: ProductSuggestion) -> str:
    if suggestion.score > 60:
        return "high"
    if suggestion.score >= 40:
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

    # Phase 2: Assemble response with confidence (purely score-based)
    position_suggestions: list[PositionSuggestions] = []
    selected_for_check: list[tuple[LVPosition, object]] = []

    for position, final_suggestions in scored_pairs:
        for s in final_suggestions:
            s.confidence = _compute_confidence(s)
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

    return SuggestionsResponse(suggestions=position_suggestions, compatibility_issues=[])



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

        custom_unit_price = request.custom_unit_prices.get(position_id)
        if custom_unit_price is not None:
            if custom_unit_price < unit_price:
                warnings.append(ExportWarning(
                    position_id=position_id,
                    ordnungszahl=position.ordnungszahl,
                    reason="VK unter EK nicht erlaubt, EK verwendet",
                ))
            unit_price = max(unit_price, custom_unit_price)

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
        bauvorhaben=p.bauvorhaben,
        objekt_nr=p.objekt_nr,
        submission_date=p.submission_date,
        kunde_name=p.kunde_name,
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(q: str = "", db: Session = Depends(get_db)) -> list[ProjectSummary]:
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
    return [_project_to_summary(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectDetailResponse:
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    positions = _reconstruct_positions(project.positions)
    metadata = ProjectMetadata(
        bauvorhaben=project.bauvorhaben,
        objekt_nr=project.objekt_nr,
        submission_date=project.submission_date,
        auftraggeber=project.auftraggeber,
        kunde_name=project.kunde_name,
        kunde_adresse=project.kunde_adresse,
    )
    selections = None
    if project.selections_json:
        try:
            selections = json.loads(project.selections_json)
        except Exception:
            pass
    return ProjectDetailResponse(
        project=_project_to_summary(project),
        positions=positions,
        metadata=metadata,
        selections=selections,
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(LVProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/projects/save-selections")
def save_selections(request: SaveSelectionsRequest, db: Session = Depends(get_db)):
    """Feature 5: Save article selections for a project (for duplicate reuse)."""
    project = db.get(LVProject, request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    project.selections_json = json.dumps(request.selected_article_ids)
    db.commit()
    return {"ok": True}


@router.post("/overrides")
def record_override(request: OverrideRequest, db: Session = Depends(get_db)):
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
def get_project_pdf(project_id: int, db: Session = Depends(get_db)):
    """Feature 8: Serve the stored PDF file for a project."""
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
        id=s.id, name=s.name, email=s.email, phone=s.phone,
        categories=cats, notes=s.notes, active=s.active,
    )


@router.get("/suppliers", response_model=list[SupplierResponse])
def list_suppliers(db: Session = Depends(get_db)):
    suppliers = db.execute(
        select(Supplier).where(Supplier.active == True).order_by(Supplier.name)
    ).scalars().all()
    return [_supplier_to_response(s) for s in suppliers]


@router.post("/suppliers", response_model=SupplierResponse)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
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
def update_supplier(supplier_id: int, data: SupplierCreate, db: Session = Depends(get_db)):
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
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status_code=404, detail="Lieferant nicht gefunden")
    s.active = False
    db.commit()
    return {"ok": True}


@router.post("/inquiries", response_model=InquiryResponse)
def create_inquiry(data: InquiryCreateRequest, db: Session = Depends(get_db)):
    from ..services.email_service import build_inquiry_email, send_email

    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Lieferant nicht gefunden")

    # Get project name for email
    project_name = None
    if data.project_id:
        project = db.get(LVProject, data.project_id)
        if project:
            project_name = project.bauvorhaben or project.project_name

    params_dict = data.technical_params.model_dump(exclude_none=True) if data.technical_params else None

    subject, body = build_inquiry_email(
        product_description=data.product_description,
        project_name=project_name,
        technical_params=params_dict,
        quantity=data.quantity,
        unit=data.unit,
        custom_message=data.custom_message,
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
    db.commit()
    db.refresh(inquiry)

    return InquiryResponse(
        id=inquiry.id,
        supplier_name=supplier.name,
        supplier_email=supplier.email,
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
        created_at=inquiry.created_at,
    )


@router.get("/inquiries", response_model=list[InquiryResponse])
def list_inquiries(
    project_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
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
            supplier_name=supplier.name if supplier else "?",
            supplier_email=supplier.email if supplier else "",
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
            created_at=inq.created_at,
        ))
    return result


@router.patch("/inquiries/{inquiry_id}/status")
def update_inquiry_status(
    inquiry_id: int,
    data: InquiryStatusUpdate,
    db: Session = Depends(get_db),
):
    inq = db.get(SupplierInquiry, inquiry_id)
    if not inq:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden")
    if data.status not in ("offen", "angefragt", "angebot_erhalten"):
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    inq.status = data.status
    if data.notes is not None:
        inq.notes = data.notes
    db.commit()
    return {"ok": True}
