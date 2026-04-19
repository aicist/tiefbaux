from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ComponentRequirement(BaseModel):
    component_name: str
    description: str | None = None
    product_category: str | None = None
    product_subcategory: str | None = None
    nominal_diameter_dn: int | None = None
    secondary_nominal_diameter_dn: int | None = None
    quantity: float | None = 1
    unit: str | None = None
    material: str | None = None
    system_family: str | None = None
    load_class: str | None = None
    dimensions: str | None = None
    connection_type: str | None = None
    installation_area: str | None = None
    compressive_strength: str | None = None
    exposition_class: str | None = None
    additional_specs: list[str] | None = None


class TechnicalParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    article_type: str | None = None
    product_category: str | None = None
    product_subcategory: str | None = None
    material: str | None = None
    nominal_diameter_dn: int | None = None
    secondary_nominal_diameter_dn: int | None = None
    load_class: str | None = None
    norm: str | None = None
    dimensions: str | None = None
    color: str | None = None
    quantity: float | None = None
    unit: str | None = None
    reference_product: str | None = None
    installation_area: str | None = None
    stiffness_class_sn: int | None = None
    sortiment_relevant: bool | None = None
    pipe_length_mm: int | None = None
    angle_deg: int | None = None
    application_area: str | None = None
    system_family: str | None = None
    connection_type: str | None = None
    seal_type: str | None = None
    compatible_systems: list[str] | None = None
    components: list[ComponentRequirement] | None = None
    variants: list[str] | None = None
    features: list[str] | None = None
    installation_notes: str | None = None
    compressive_strength: str | None = None
    exposition_class: str | None = None
    additional_specs: list[str] | None = None


class LVPosition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    ordnungszahl: str
    description: str
    raw_text: str
    quantity: float | None = None
    unit: str | None = None
    billable: bool = True
    position_type: Literal["material", "dienstleistung"] | None = None
    parameters: TechnicalParameters = Field(default_factory=TechnicalParameters)
    source_page: int | None = None
    source_y: int | None = None


class DuplicateInfo(BaseModel):
    is_duplicate: bool
    project_id: int | None = None
    project_name: str | None = None
    created_at: datetime | None = None
    total_positions: int | None = None


class ProjectMetadata(BaseModel):
    bauvorhaben: str | None = None
    objekt_nr: str | None = None
    submission_date: str | None = None
    auftraggeber: str | None = None
    kunde_name: str | None = None
    kunde_adresse: str | None = None


class ParseLVResponse(BaseModel):
    positions: list[LVPosition]
    total_positions: int
    billable_positions: int
    service_positions: int = 0
    duplicate: DuplicateInfo | None = None
    metadata: ProjectMetadata | None = None


class ScoreBreakdown(BaseModel):
    component: str
    points: float
    detail: str


class ProductSuggestion(BaseModel):
    artikel_id: str
    artikelname: str
    hersteller: str | None = None
    category: str | None = None
    subcategory: str | None = None
    dn: int | None = None
    sn: int | None = None
    load_class: str | None = None
    norm: str | None = None
    material: str | None = None
    angle_deg: int | None = None
    stock: int | None = None
    delivery_days: int | None = None
    price_net: float | None = None
    total_net: float | None = None
    currency: str = "EUR"
    score: float
    confidence: str | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score_breakdown: list[ScoreBreakdown] = Field(default_factory=list)
    is_override: bool = False
    is_supplier_offer: bool = False
    is_bogen_fallback: bool = False
    supplier_offer_id: int | None = None
    supplier_name: str | None = None


class ComponentSuggestions(BaseModel):
    component_name: str
    quantity: float | None = 1
    suggestions: list[ProductSuggestion] = Field(default_factory=list)


class PositionSuggestions(BaseModel):
    position_id: str
    ordnungszahl: str
    description: str
    suggestions: list[ProductSuggestion] = Field(default_factory=list)
    component_suggestions: list[ComponentSuggestions] | None = None


class SuggestionsRequest(BaseModel):
    positions: list[LVPosition]
    project_id: int | None = None


class SuggestionsResponse(BaseModel):
    suggestions: list[PositionSuggestions]


class ExportOfferRequest(BaseModel):
    positions: list[LVPosition]
    selected_article_ids: dict[str, list[str]]
    assignment_keys_by_position: dict[str, list[str]] = Field(default_factory=dict)
    custom_unit_prices: dict[str, float] = Field(default_factory=dict)
    customer_name: str | None = None
    customer_address: str | None = None
    project_name: str | None = None
    alternative_flags: dict[str, bool] = Field(default_factory=dict)
    supplier_open_flags: dict[str, bool] = Field(default_factory=dict)
    rejected_position_ids: list[str] = Field(default_factory=list)
    project_id: int | None = None


class OfferLine(BaseModel):
    ordnungszahl: str
    description: str
    quantity: float
    unit: str
    artikel_id: str
    artikelname: str
    hersteller: str | None = None
    price_net: float
    total_net: float
    is_additional: bool = False
    is_alternative: bool = False
    supplier_open: bool = False


class ExportOfferMetadata(BaseModel):
    customer_name: str | None = None
    customer_address: str | None = None
    project_name: str | None = None
    created_at: datetime
    total_net: float


class ExportWarning(BaseModel):
    position_id: str
    ordnungszahl: str
    reason: str


class OfferEmailDefaults(BaseModel):
    customer_email: str | None = None
    subject: str
    body: str


class ExportPreviewResponse(BaseModel):
    included_count: int
    total_count: int
    skipped_positions: list[ExportWarning] = Field(default_factory=list)
    total_net: float
    email_defaults: OfferEmailDefaults | None = None


class SendOfferEmailRequest(ExportOfferRequest):
    customer_email: str
    email_subject: str
    email_body: str


class SendOfferEmailResponse(BaseModel):
    sent: bool
    saved: bool
    detail: str | None = None


class ProductSearchResult(BaseModel):
    artikel_id: str
    artikelname: str
    hersteller: str | None = None
    kategorie: str | None = None
    nennweite_dn: int | None = None
    belastungsklasse: str | None = None
    vk_listenpreis_netto: float | None = None
    lager_gesamt: int | None = None
    waehrung: str | None = None
    steifigkeitsklasse_sn: str | None = None
    norm_primaer: str | None = None
    werkstoff: str | None = None


class ProductSearchResponse(BaseModel):
    items: list[ProductSearchResult] = Field(default_factory=list)
    has_more: bool = False


class HealthResponse(BaseModel):
    status: str


class ProjectSummary(BaseModel):
    id: int
    filename: str | None = None
    project_name: str | None = None
    projekt_nr: str | None = None
    total_positions: int
    billable_positions: int
    service_positions: int
    created_at: datetime
    bauvorhaben: str | None = None
    objekt_nr: str | None = None
    submission_date: str | None = None
    kunde_name: str | None = None
    status: str = "neu"
    anfrage_art: str = "submission"
    offer_pdf_path: str | None = None
    assigned_user_name: str | None = None
    last_editor_name: str | None = None
    last_edited_at: datetime | None = None


class KundenOrdnerSummary(BaseModel):
    kunde_id: int
    slug: str
    name: str
    display_name: str | None = None
    email_domain: str | None = None
    project_count: int
    latest_project_created_at: datetime | None = None


class ObjektSummary(BaseModel):
    id: int
    slug: str
    bauvorhaben: str | None = None
    objekt_nr: str | None = None
    auftraggeber: str | None = None
    submission_date: str | None = None
    created_at: datetime
    kunden_count: int
    project_count: int
    latest_project_created_at: datetime | None = None


class ObjektDetailResponse(BaseModel):
    objekt: ObjektSummary
    kunden: list[KundenOrdnerSummary] = Field(default_factory=list)


class KundenProjektListResponse(BaseModel):
    objekt: ObjektSummary
    kunde: KundenOrdnerSummary
    projects: list[ProjectSummary] = Field(default_factory=list)


class ObjektUpdate(BaseModel):
    bauvorhaben: str | None = None
    objekt_nr: str | None = None
    auftraggeber: str | None = None
    submission_date: str | None = None


class KundeUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    email_domain: str | None = None
    address: str | None = None


class ProjectUpdate(BaseModel):
    project_name: str | None = None
    bauvorhaben: str | None = None
    submission_date: str | None = None
    anfrage_art: str | None = None


class AssignmentUiState(BaseModel):
    active_filter: Literal["alle", "zugeordnet", "offen", "dienstleistung"] = "alle"
    current_position_id: str | None = None
    is_finished: bool = False


class ProjectDetailResponse(BaseModel):
    project: ProjectSummary
    positions: list[LVPosition]
    metadata: ProjectMetadata | None = None
    selections: dict[str, list[str]] | None = None
    decisions: dict[str, Literal["accepted", "rejected", "inquiry_pending"]] | None = None
    component_selections: dict[str, str] | None = None
    ui_state: AssignmentUiState | None = None


class SaveSelectionsRequest(BaseModel):
    project_id: int
    selected_article_ids: dict[str, list[str]]


class SaveWorkstateRequest(BaseModel):
    project_id: int
    selected_article_ids: dict[str, list[str]] = Field(default_factory=dict)
    decisions: dict[str, Literal["accepted", "rejected", "inquiry_pending"]] = Field(default_factory=dict)
    component_selections: dict[str, str] = Field(default_factory=dict)
    ui_state: AssignmentUiState | None = None


class OverrideRequest(BaseModel):
    position_description: str
    ordnungszahl: str | None = None
    category: str | None = None
    dn: int | None = None
    material: str | None = None
    chosen_artikel_id: str


# --- Supplier & Inquiry ---

class SupplierCreate(BaseModel):
    name: str
    email: str
    phone: str | None = None
    categories: list[str] = Field(default_factory=list)
    notes: str | None = None


class SupplierResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None = None
    categories: list[str] = Field(default_factory=list)
    notes: str | None = None
    active: bool


class InquiryCreateRequest(BaseModel):
    supplier_id: int
    project_id: int | None = None
    position_id: str | None = None
    ordnungszahl: str | None = None
    product_description: str
    technical_params: TechnicalParameters | None = None
    quantity: float | None = None
    unit: str | None = None
    custom_message: str | None = None
    send_email: bool = True


class InquiryBatchCreateRequest(BaseModel):
    supplier_ids: list[int]
    project_id: int | None = None
    position_id: str | None = None
    ordnungszahl: str | None = None
    product_description: str
    technical_params: TechnicalParameters | None = None
    quantity: float | None = None
    unit: str | None = None
    custom_message: str | None = None


class BatchSendRequest(BaseModel):
    project_id: int
    email_overrides: dict[int, dict[str, str]] = Field(default_factory=dict)
    """Optional per-supplier overrides: {supplier_id: {subject: ..., body: ...}}"""
    simulate_only: bool = False
    """When true, do not send real emails; only persist the inquiry as sent."""


class BatchSendResponse(BaseModel):
    sent_count: int
    failed_count: int


class BundledEmailPreview(BaseModel):
    supplier_id: int
    supplier_name: str
    supplier_email: str
    subject: str
    body: str
    inquiry_ids: list[int] = Field(default_factory=list)
    positions: list[dict] = Field(default_factory=list)


class InquiryResponse(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    supplier_email: str
    project_id: int | None = None
    position_id: str | None = None
    ordnungszahl: str | None = None
    product_description: str
    quantity: float | None = None
    unit: str | None = None
    status: str
    sent_at: datetime | None = None
    email_subject: str | None = None
    email_body: str | None = None
    notes: str | None = None
    created_at: datetime


class InquiryStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class InquiryContentUpdate(BaseModel):
    email_subject: str | None = None
    email_body: str | None = None
    product_description: str | None = None


class InquiryCleanupRequest(BaseModel):
    project_id: int
    position_id: str


# --- Supplier Offers ---

class SupplierOfferCreate(BaseModel):
    inquiry_id: int | None = None
    supplier_id: int
    project_id: int | None = None
    position_id: str | None = None
    ordnungszahl: str | None = None
    article_name: str
    article_number: str | None = None
    unit_price: float | None = None
    total_price: float | None = None
    delivery_days: int | None = None
    quantity: float | None = None
    unit: str | None = None
    notes: str | None = None
    source: str = "manual"


class SupplierOfferResponse(BaseModel):
    id: int
    inquiry_id: int | None = None
    supplier_id: int
    supplier_name: str
    project_id: int | None = None
    position_id: str | None = None
    ordnungszahl: str | None = None
    article_name: str
    article_number: str | None = None
    unit_price: float | None = None
    total_price: float | None = None
    delivery_days: int | None = None
    quantity: float | None = None
    unit: str | None = None
    notes: str | None = None
    source: str
    status: str
    created_at: datetime


class SupplierOfferStatusUpdate(BaseModel):
    status: Literal["neu", "zugeordnet", "abgelehnt"]


# --- Objektradar / Tenders ---

class TenderResponse(BaseModel):
    id: int
    external_id: str
    title: str
    description: str | None = None
    auftraggeber: str | None = None
    ort: str | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    submission_deadline: str | None = None
    publication_date: str | None = None
    url: str | None = None
    status: str = "neu"
    relevance_score: int = 0
    lat: float | None = None
    lng: float | None = None
    created_at: datetime | None = None
    project_id: int | None = None


class TenderStatusUpdate(BaseModel):
    status: str


# --- Auth & Users ---

class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    active: bool

class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str = "mitarbeiter"

class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class AssignProjectRequest(BaseModel):
    user_id: int | None = None
