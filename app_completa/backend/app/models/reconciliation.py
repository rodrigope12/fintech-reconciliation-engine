"""Reconciliation result models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .enums import (
    CommitStatus,
    MatchConfidence,
    ReconciliationStatus,
    AuditAction,
    SolverPhase,
)


@dataclass
class MatchedPair:
    """A confirmed match between invoice(s) and payment(s)."""
    id: str = field(default_factory=lambda: str(uuid4()))

    # Matched transactions
    invoice_ids: List[str] = field(default_factory=list)
    payment_ids: List[str] = field(default_factory=list)

    # Amounts (in cents)
    total_invoice_cents: int = 0
    total_payment_cents: int = 0
    gap_cents: int = 0  # gamma: operational gap (FX, fees)

    # Quality
    semantic_score: float = 0.0
    confidence: MatchConfidence = MatchConfidence.MEDIUM
    commit_status: CommitStatus = CommitStatus.SOFT

    # Audit
    matched_at: datetime = field(default_factory=datetime.utcnow)
    matched_by: str = "system"  # "safe_peeling", "milp_solver", "manual"
    match_reason: str = ""

    @property
    def is_exact(self) -> bool:
        """Check if amounts match exactly (no gap)."""
        return self.gap_cents == 0

    @property
    def cardinality(self) -> int:
        """Number of documents involved in this match."""
        return len(self.invoice_ids) + len(self.payment_ids)


@dataclass
class PartialMatch:
    """A match with remaining balance (partial payment)."""
    id: str = field(default_factory=lambda: str(uuid4()))

    # Base match
    invoice_id: str = ""
    payment_ids: List[str] = field(default_factory=list)

    # Amounts (in cents)
    invoice_amount_cents: int = 0
    paid_amount_cents: int = 0
    remainder_cents: int = 0

    # Quality
    semantic_score: float = 0.0
    confidence: MatchConfidence = MatchConfidence.MEDIUM

    # Is partial expected?
    partial_expected: bool = False  # True if MetodoPago == PPD

    # Audit
    matched_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def percentage_paid(self) -> float:
        """Percentage of invoice that has been paid."""
        if self.invoice_amount_cents == 0:
            return 0.0
        return (self.paid_amount_cents / self.invoice_amount_cents) * 100


@dataclass
class AmbiguousCase:
    """A case requiring manual review."""
    id: str = field(default_factory=lambda: str(uuid4()))

    # Involved transactions
    invoice_ids: List[str] = field(default_factory=list)
    payment_ids: List[str] = field(default_factory=list)

    # Why it's ambiguous
    reason: str = ""
    possible_matches: List[Dict[str, Any]] = field(default_factory=list)

    # Solver info
    solver_delta_cents: int = 0  # Error if forced to solve
    best_score: float = 0.0

    # Resolution
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution: Optional[str] = None


@dataclass
class AuditEntry:
    """An entry in the audit log."""
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Action
    action: AuditAction = AuditAction.TRANSACTION_INGESTED

    # Context
    transaction_ids: List[str] = field(default_factory=list)
    cluster_id: Optional[str] = None
    solver_phase: Optional[SolverPhase] = None

    # Details
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    # Outcome
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class ClusterResult:
    """Result of solving a single cluster."""
    cluster_id: str = field(default_factory=lambda: str(uuid4()))

    # Cluster composition
    invoice_ids: List[str] = field(default_factory=list)
    payment_ids: List[str] = field(default_factory=list)
    cluster_size: int = 0

    # Solver phases
    phase1_delta: int = 0  # Minimum error achieved
    phase1_gamma: int = 0  # Minimum gap achieved
    phase2_cardinality: int = 0  # Minimum cardinality achieved
    phase3_score: float = 0.0  # Maximum semantic score

    # Results
    matched_pairs: List[MatchedPair] = field(default_factory=list)
    partial_matches: List[PartialMatch] = field(default_factory=list)
    unmatched_invoices: List[str] = field(default_factory=list)
    unmatched_payments: List[str] = field(default_factory=list)

    # Rescue loop
    rescue_triggered: bool = False
    rescue_iterations: int = 0

    # Timing
    solve_time_ms: int = 0


@dataclass
class ReconciliationSummary:
    """Summary statistics of reconciliation."""
    # Counts
    total_invoices: int = 0
    total_payments: int = 0
    matched_invoices: int = 0
    matched_payments: int = 0
    partial_invoices: int = 0
    unmatched_invoices: int = 0
    unmatched_payments: int = 0
    manual_review_count: int = 0

    # Amounts (in cents)
    total_invoice_amount_cents: int = 0
    total_payment_amount_cents: int = 0
    matched_amount_cents: int = 0
    unmatched_invoice_amount_cents: int = 0
    unmatched_payment_amount_cents: int = 0
    remainder_amount_cents: int = 0
    total_gap_cents: int = 0
    total_error_cents: int = 0

    # Quality
    avg_semantic_score: float = 0.0
    avg_cardinality: float = 0.0
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0

    # Performance
    processing_time_seconds: float = 0.0
    clusters_processed: int = 0
    rescue_loops_triggered: int = 0

    @property
    def match_rate_invoices(self) -> float:
        """Percentage of invoices matched."""
        if self.total_invoices == 0:
            return 0.0
        return (self.matched_invoices / self.total_invoices) * 100

    @property
    def match_rate_payments(self) -> float:
        """Percentage of payments matched."""
        if self.total_payments == 0:
            return 0.0
        return (self.matched_payments / self.total_payments) * 100

    @property
    def match_rate_amount(self) -> float:
        """Percentage of invoice amount matched."""
        if self.total_invoice_amount_cents == 0:
            return 0.0
        return (self.matched_amount_cents / self.total_invoice_amount_cents) * 100


@dataclass
class ReconciliationResult:
    """Complete result of a reconciliation job."""
    job_id: str = field(default_factory=lambda: str(uuid4()))

    # Status
    status: ReconciliationStatus = ReconciliationStatus.COMPLETED

    # Results
    matched_pairs: List[MatchedPair] = field(default_factory=list)
    partial_matches: List[PartialMatch] = field(default_factory=list)
    unmatched_invoices: List[str] = field(default_factory=list)
    unmatched_payments: List[str] = field(default_factory=list)
    manual_review: List[AmbiguousCase] = field(default_factory=list)

    # Cluster results (for detailed analysis)
    cluster_results: List[ClusterResult] = field(default_factory=list)

    # Summary
    summary: ReconciliationSummary = field(default_factory=ReconciliationSummary)

    # Audit
    audit_log: List[AuditEntry] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Error handling
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ReconciliationJob:
    """A reconciliation job request."""
    id: str = field(default_factory=lambda: str(uuid4()))

    # Input
    bank_files: List[str] = field(default_factory=list)

    # Facturama credentials
    rfc: str = ""
    # Note: password handled separately for security

    # Date range
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    # Status
    status: ReconciliationStatus = ReconciliationStatus.PENDING
    progress: float = 0.0  # 0-100
    current_phase: str = ""

    # Result
    result: Optional[ReconciliationResult] = None

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
