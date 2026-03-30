from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="mitarbeiter")  # 'admin' | 'mitarbeiter'
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    artikel_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ean_gtin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    hersteller: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    hersteller_artikelnr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artikelname: Mapped[str] = mapped_column(String(256), index=True)
    artikelbeschreibung: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kategorie: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    unterkategorie: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    werkstoff: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    nennweite_dn: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    nennweite_od: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    laenge_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    breite_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hoehe_mm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wandstaerke_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gewicht_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    belastungsklasse: Mapped[Optional[str]] = mapped_column(String(16), index=True, nullable=True)
    steifigkeitsklasse_sn: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    norm_primaer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    norm_sekundaer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    system_familie: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verbindungstyp: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dichtungstyp: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kompatible_dn_anschluss: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kompatible_systeme: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    einsatzbereich: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    einbauort: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ek_netto: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vk_listenpreis_netto: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    staffelpreis_ab_10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    staffelpreis_ab_50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    staffelpreis_ab_100: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    waehrung: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    preiseinheit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lager_rheinbach: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lager_duesseldorf: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lager_gesamt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lieferant_1_lieferzeit_tage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    ersatz_artikel_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    nachfolger_artikel_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


Index("ix_products_category_dn", Product.kategorie, Product.unterkategorie, Product.nennweite_dn)


class LVProject(Base):
    __tablename__ = "lv_projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    total_positions: Mapped[int] = mapped_column(Integer, default=0)
    billable_positions: Mapped[int] = mapped_column(Integer, default=0)
    service_positions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Feature 1+4: Project metadata from LV
    bauvorhaben: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    objekt_nr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    submission_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    auftraggeber: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    kunde_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    kunde_adresse: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Auto-generated project number (P-YYMM-NNN)
    projekt_nr: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, unique=True)

    # Feature 5: Stored article selections for duplicate reuse
    selections_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Persisted assignment workstate (selections, decisions, component selections)
    workstate_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Feature 8: PDF storage
    pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Project status: "neu", "offen", "anfrage_offen", "gerechnet"
    status: Mapped[str] = mapped_column(String(16), default="neu", index=True)

    # Offer PDF storage
    offer_pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # User tracking
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_editor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    positions = relationship("LVProjectPosition", back_populates="project", cascade="all, delete-orphan")
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    last_editor = relationship("User", foreign_keys=[last_editor_id])


class LVProjectPosition(Base):
    __tablename__ = "lv_project_positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("lv_projects.id"), index=True)
    position_id: Mapped[str] = mapped_column(String(64))
    ordnungszahl: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    billable: Mapped[bool] = mapped_column(default=True)
    position_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    parameters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Feature 10: Source page number from PDF
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    project = relationship("LVProject", back_populates="positions")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    email: Mapped[str] = mapped_column(String(256))
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    categories_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupplierInquiry(Base):
    __tablename__ = "supplier_inquiries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lv_projects.id"), nullable=True, index=True)
    position_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ordnungszahl: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    product_description: Mapped[str] = mapped_column(Text)
    technical_params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="offen")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    email_subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    email_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier")
    project = relationship("LVProject")


class InboundEmailEvent(Base):
    __tablename__ = "inbound_email_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    mailbox: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    sender: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Tender(Base):
    """Objektradar: Öffentliche Ausschreibungen aus Vergabe.NRW."""
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auftraggeber: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    ort: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    cpv_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    submission_deadline: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    publication_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="neu", index=True)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lv_projects.id"), nullable=True)

    project = relationship("LVProject")


class SupplierOffer(Base):
    """Structured offer received from a supplier in response to an inquiry."""
    __tablename__ = "supplier_offers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    inquiry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("supplier_inquiries.id"), nullable=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("lv_projects.id"), nullable=True, index=True)
    position_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ordnungszahl: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    article_name: Mapped[str] = mapped_column(String(512))
    article_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | email_auto | pdf_import
    status: Mapped[str] = mapped_column(String(32), default="neu")  # neu | zugeordnet | abgelehnt

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier")
    inquiry = relationship("SupplierInquiry")
    project = relationship("LVProject")


class ManualOverride(Base):
    """Feature 6: Tracks manual product selections by employees for learning."""
    __tablename__ = "manual_overrides"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    description_hash: Mapped[str] = mapped_column(String(64), index=True)
    ordnungszahl_pattern: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    material: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chosen_artikel_id: Mapped[str] = mapped_column(String(32), index=True)
    override_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
