"""Enumerations for the financial reconciliation system."""

from enum import Enum


class CommitStatus(str, Enum):
    """
    Status of a reconciliation commit.

    SHADOW: Provisional match in buffer zone (T to T+5), reversible
    SOFT: Match in recent zone (T-2 to T), reversible if better match found
    HARD: Definitive match (before T-2), irreversible
    PENDING: Not yet processed
    MANUAL_REVIEW: Requires human intervention
    """
    SHADOW = "shadow"
    SOFT = "soft"
    HARD = "hard"
    PENDING = "pending"
    MANUAL_REVIEW = "manual_review"


class MetodoPago(str, Enum):
    """
    CFDI payment method (MetodoPago field).

    PUE: Pago en Una sola Exhibicion (single payment)
    PPD: Pago en Parcialidades o Diferido (partial/deferred payment)
    """
    PUE = "PUE"
    PPD = "PPD"


class MatchConfidence(str, Enum):
    """Confidence level of a match."""
    HIGH = "high"          # ID match or unique amount + text
    MEDIUM = "medium"      # MILP solution with good score
    LOW = "low"            # MILP solution with poor score
    AMBIGUOUS = "ambiguous"  # Multiple valid solutions


class TransactionSource(str, Enum):
    """Source of the transaction."""
    BANK = "bank"          # Bank statement (PDF/OCR)
    CFDI = "cfdi"          # Electronic invoice (XML)
    MANUAL = "manual"      # Manual entry


class TransactionType(str, Enum):
    """Type of transaction."""
    DEBIT = "debit"        # Money out (payment made)
    CREDIT = "credit"      # Money in (payment received)


class ReconciliationStatus(str, Enum):
    """Status of a reconciliation job."""
    PENDING = "pending"
    PROCESSING = "processing"
    INGESTING = "ingesting"
    PEELING = "peeling"
    CLUSTERING = "clustering"
    SOLVING = "solving"
    RESCUE = "rescue"
    COMPLETED = "completed"
    FAILED = "failed"


class SolverPhase(str, Enum):
    """Phase of the lexicographic MILP solver."""
    PHASE_1_MINIMIZE_ERROR = "phase_1_minimize_error"
    PHASE_2_MINIMIZE_CARDINALITY = "phase_2_minimize_cardinality"
    PHASE_3_MAXIMIZE_SCORE = "phase_3_maximize_score"


class AuditAction(str, Enum):
    """Type of audit action."""
    TRANSACTION_INGESTED = "transaction_ingested"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    OCR_CORRECTION = "ocr_correction"
    SAFE_PEEL_MATCH = "safe_peel_match"
    CLUSTER_CREATED = "cluster_created"
    SOLVER_STARTED = "solver_started"
    SOLVER_PHASE_COMPLETED = "solver_phase_completed"
    MATCH_COMMITTED = "match_committed"
    MATCH_PROMOTED = "match_promoted"
    RESCUE_TRIGGERED = "rescue_triggered"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
