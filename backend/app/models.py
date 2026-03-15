from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


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

    # Feature 5: Stored article selections for duplicate reuse
    selections_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Feature 8: PDF storage
    pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    positions = relationship("LVProjectPosition", back_populates="project", cascade="all, delete-orphan")


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
