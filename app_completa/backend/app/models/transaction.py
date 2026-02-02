"""Transaction models for the financial reconciliation system."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

import numpy as np

from .enums import (
    CommitStatus,
    MetodoPago,
    TransactionSource,
    TransactionType,
    MatchConfidence,
)


@dataclass
class Transaction:
    """
    Base transaction model with all fields needed for reconciliation.
    All monetary amounts are stored in CENTS (integer) to avoid floating point errors.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid4()))
    external_id: Optional[str] = None  # Bank reference or CFDI UUID

    # Source
    source: TransactionSource = TransactionSource.BANK
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    source_row: Optional[int] = None

    # Financial data (ALL IN CENTS - integers only)
    amount_cents: int = 0
    currency: str = "MXN"
    transaction_type: TransactionType = TransactionType.DEBIT

    # Temporal
    transaction_date: Optional[date] = None
    value_date: Optional[date] = None  # For bank statements

    # Counterparty
    counterparty_name: Optional[str] = None
    counterparty_rfc: Optional[str] = None

    # Description
    description: str = ""
    reference: Optional[str] = None

    # For CFDIs
    metodo_pago: Optional[MetodoPago] = None
    forma_pago: Optional[str] = None

    # NLP
    embedding: Optional[np.ndarray] = None
    normalized_text: str = ""

    # OCR confidence (for bank statements)
    ocr_confidence: float = 1.0

    # Reconciliation state
    commit_status: CommitStatus = CommitStatus.PENDING
    matched_to: Optional[str] = None  # ID of matched transaction
    match_confidence: Optional[MatchConfidence] = None
    remainder_cents: int = 0  # For partial payments

    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def amount(self) -> float:
        """Return amount in standard units (pesos)."""
        return self.amount_cents / 100.0

    @property
    def remainder(self) -> float:
        """Return remainder in standard units (pesos)."""
        return self.remainder_cents / 100.0

    @property
    def is_partial(self) -> bool:
        """Check if this transaction has a partial payment."""
        return self.remainder_cents > 0

    @property
    def is_committed(self) -> bool:
        """Check if this transaction has been committed (any level)."""
        return self.commit_status in (
            CommitStatus.SHADOW,
            CommitStatus.SOFT,
            CommitStatus.HARD,
        )

    @property
    def is_reversible(self) -> bool:
        """Check if the commit can be reversed."""
        return self.commit_status in (
            CommitStatus.SHADOW,
            CommitStatus.SOFT,
        )

    @property
    def expects_partial_payment(self) -> bool:
        """Check if partial payments are expected (PPD method)."""
        return self.metodo_pago == MetodoPago.PPD

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "external_id": self.external_id,
            "source": self.source.value,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "currency": self.currency,
            "transaction_type": self.transaction_type.value,
            "transaction_date": self.transaction_date.isoformat() if self.transaction_date else None,
            "counterparty_name": self.counterparty_name,
            "counterparty_rfc": self.counterparty_rfc,
            "description": self.description,
            "reference": self.reference,
            "metodo_pago": self.metodo_pago.value if self.metodo_pago else None,
            "commit_status": self.commit_status.value,
            "matched_to": self.matched_to,
            "match_confidence": self.match_confidence.value if self.match_confidence else None,
            "remainder_cents": self.remainder_cents,
            "ocr_confidence": self.ocr_confidence,
        }


@dataclass
class BankTransaction(Transaction):
    """
    Transaction extracted from bank statement PDF via OCR.
    Includes validation metadata.
    """
    source: TransactionSource = TransactionSource.BANK

    # Balance tracking for algebraic validation
    balance_before_cents: Optional[int] = None
    balance_after_cents: Optional[int] = None

    # OCR metadata
    ocr_raw_text: str = ""
    ocr_bounding_box: Optional[Dict[str, float]] = None

    # Validation
    is_validated: bool = False
    validation_method: Optional[str] = None

    # Shadow record for OCR corrections
    shadow_amount_cents: Optional[int] = None  # Corrected amount if OCR failed
    shadow_confidence: float = 0.0

    @property
    def passes_recurrence_check(self) -> bool:
        """
        Check if transaction passes balance recurrence equation.
        B_t = B_{t-1} + (credit - debit)
        """
        if self.balance_before_cents is None or self.balance_after_cents is None:
            return False

        expected_change = self.amount_cents
        if self.transaction_type == TransactionType.DEBIT:
            expected_change = -expected_change

        actual_change = self.balance_after_cents - self.balance_before_cents
        return expected_change == actual_change


@dataclass
class CFDITransaction(Transaction):
    """
    Transaction from CFDI (electronic invoice) XML.
    """
    source: TransactionSource = TransactionSource.CFDI

    # CFDI specific fields
    cfdi_uuid: Optional[str] = None
    cfdi_version: str = "4.0"
    cfdi_tipo: str = "I"  # I=Ingreso, E=Egreso, P=Pago

    # Emisor (issuer)
    emisor_rfc: Optional[str] = None
    emisor_nombre: Optional[str] = None

    # Receptor (recipient)
    receptor_rfc: Optional[str] = None
    receptor_nombre: Optional[str] = None

    # Amounts breakdown
    subtotal_cents: int = 0
    total_impuestos_cents: int = 0
    descuento_cents: int = 0

    # Dates
    fecha_emision: Optional[datetime] = None
    fecha_timbrado: Optional[datetime] = None

    # Conceptos (line items)
    conceptos: List[Dict[str, Any]] = field(default_factory=list)

    # Complemento de pago (for payment CFDIs)
    es_complemento_pago: bool = False
    doctos_relacionados: List[str] = field(default_factory=list)  # UUIDs


@dataclass
class TransactionMatch:
    """
    Represents a potential match between transactions.
    Used during Safe Peeling and MILP solving.
    """
    invoice_id: str
    payment_id: str

    # Scores
    semantic_score: float = 0.0  # 0-1, from embeddings
    temporal_score: float = 0.0  # 0-1, based on date proximity
    reference_score: float = 0.0  # 0-1, based on ID/reference match
    combined_score: float = 0.0

    # Match details
    amount_difference_cents: int = 0
    days_apart: int = 0

    # MILP solution values
    is_selected: bool = False
    remainder_cents: int = 0

    # Confidence
    confidence: MatchConfidence = MatchConfidence.LOW

    def calculate_combined_score(
        self,
        semantic_weight: float = 0.5,
        temporal_weight: float = 0.3,
        reference_weight: float = 0.2,
    ) -> float:
        """Calculate weighted combined score."""
        self.combined_score = (
            self.semantic_score * semantic_weight +
            self.temporal_score * temporal_weight +
            self.reference_score * reference_weight
        )
        return self.combined_score
