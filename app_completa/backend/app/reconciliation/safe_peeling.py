"""
Safe Peeling Engine - Phase 0 of the reconciliation pipeline.

Implements the V3.0 Rolling Window with V9.3 Orthogonal Validation.
Uses Shadow/Soft/Hard commit strategy for reversible matches.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Dict, Set, Tuple, Optional

import structlog
from rapidfuzz import fuzz

from ..config import get_settings
from ..models import (
    Transaction,
    CommitStatus,
    MatchConfidence,
    TransactionType,
    MatchedPair,
    AuditEntry,
    AuditAction,
)

logger = structlog.get_logger()


@dataclass
class PeelingResult:
    """Result of safe peeling phase."""
    matched_pairs: List[MatchedPair]
    remaining_invoices: List[Transaction]
    remaining_payments: List[Transaction]
    audit_entries: List[AuditEntry]
    stats: Dict[str, int]


@dataclass
class CandidateMatch:
    """A potential match candidate."""
    invoice: Transaction
    payment: Transaction
    amount_match: bool
    reference_match: bool
    text_similarity: float
    days_apart: int
    is_unique_amount: bool


class SafePeelingEngine:
    """
    Phase 0: Safe Peeling with Rolling Window.

    Commits only high-confidence matches:
    1. Exact ID/reference matches
    2. Unique amount matches with orthogonal text validation

    Commit levels:
    - HARD: Transactions older than T - hard_threshold
    - SOFT: Transactions between T - hard_threshold and T
    - SHADOW: Transactions in buffer zone (T to T + buffer_days)
    """

    def __init__(self):
        self.settings = get_settings()
        self.buffer_days = self.settings.buffer_days
        self.hard_threshold = self.settings.hard_commit_threshold_days
        self.uniqueness_window = self.settings.uniqueness_window_days
        self.text_threshold = self.settings.text_similarity_threshold

    def process(
        self,
        invoices: List[Transaction],
        payments: List[Transaction],
        reference_date: Optional[date] = None,
    ) -> PeelingResult:
        """
        Execute safe peeling on transactions.

        Args:
            invoices: List of invoice transactions (debts)
            payments: List of payment transactions (credits)
            reference_date: Reference date T (defaults to today)

        Returns:
            PeelingResult with matches and remaining transactions
        """
        logger.info(
            "Starting safe peeling",
            invoices=len(invoices),
            payments=len(payments),
        )

        if reference_date is None:
            reference_date = date.today()

        matched_pairs = []
        audit_entries = []
        matched_invoice_ids: Set[str] = set()
        matched_payment_ids: Set[str] = set()

        # Build indices for efficient lookup
        payment_by_amount = self._build_amount_index(payments)
        payment_by_reference = self._build_reference_index(payments)

        # Pre-compute amount uniqueness
        amount_counts = self._count_amounts_in_window(
            invoices + payments,
            reference_date,
        )

        # Process each invoice
        for invoice in invoices:
            if invoice.id in matched_invoice_ids:
                continue

            # Strategy 1: Exact reference match
            match = self._try_reference_match(
                invoice,
                payment_by_reference,
                matched_payment_ids,
            )

            # Strategy 2: Unique amount with orthogonal validation
            if not match:
                match = self._try_unique_amount_match(
                    invoice,
                    payment_by_amount,
                    amount_counts,
                    matched_payment_ids,
                    reference_date,
                )

            if match:
                # Determine commit status based on dates
                commit_status = self._determine_commit_status(
                    invoice, match.payment, reference_date
                )

                # Create matched pair
                pair = MatchedPair(
                    invoice_ids=[invoice.id],
                    payment_ids=[match.payment.id],
                    total_invoice_cents=invoice.amount_cents,
                    total_payment_cents=match.payment.amount_cents,
                    gap_cents=invoice.amount_cents - match.payment.amount_cents,
                    semantic_score=match.text_similarity,
                    confidence=MatchConfidence.HIGH if match.reference_match else MatchConfidence.MEDIUM,
                    commit_status=commit_status,
                    matched_by="safe_peeling",
                    match_reason=self._build_match_reason(match),
                )

                matched_pairs.append(pair)
                matched_invoice_ids.add(invoice.id)
                matched_payment_ids.add(match.payment.id)

                # Update transaction states
                invoice.commit_status = commit_status
                invoice.matched_to = match.payment.id
                invoice.match_confidence = pair.confidence

                match.payment.commit_status = commit_status
                match.payment.matched_to = invoice.id
                match.payment.match_confidence = pair.confidence

                # Audit
                audit_entries.append(AuditEntry(
                    action=AuditAction.SAFE_PEEL_MATCH,
                    transaction_ids=[invoice.id, match.payment.id],
                    message=f"Safe peel match: {pair.match_reason}",
                    details={
                        "commit_status": commit_status.value,
                        "text_similarity": match.text_similarity,
                        "is_unique_amount": match.is_unique_amount,
                        "reference_match": match.reference_match,
                    },
                ))

        # Collect remaining transactions
        remaining_invoices = [
            inv for inv in invoices if inv.id not in matched_invoice_ids
        ]
        remaining_payments = [
            pay for pay in payments if pay.id not in matched_payment_ids
        ]

        stats = {
            "total_invoices": len(invoices),
            "total_payments": len(payments),
            "matched": len(matched_pairs),
            "remaining_invoices": len(remaining_invoices),
            "remaining_payments": len(remaining_payments),
            "hard_commits": sum(1 for p in matched_pairs if p.commit_status == CommitStatus.HARD),
            "soft_commits": sum(1 for p in matched_pairs if p.commit_status == CommitStatus.SOFT),
            "shadow_commits": sum(1 for p in matched_pairs if p.commit_status == CommitStatus.SHADOW),
        }

        logger.info("Safe peeling complete", **stats)

        return PeelingResult(
            matched_pairs=matched_pairs,
            remaining_invoices=remaining_invoices,
            remaining_payments=remaining_payments,
            audit_entries=audit_entries,
            stats=stats,
        )

    def _build_amount_index(
        self,
        transactions: List[Transaction],
    ) -> Dict[int, List[Transaction]]:
        """Build index of transactions by amount."""
        index = defaultdict(list)
        for txn in transactions:
            index[txn.amount_cents].append(txn)
        return index

    def _build_reference_index(
        self,
        transactions: List[Transaction],
    ) -> Dict[str, Transaction]:
        """Build index of transactions by reference/external_id."""
        index = {}
        for txn in transactions:
            if txn.external_id:
                index[txn.external_id.lower()] = txn
            if txn.reference:
                index[txn.reference.lower()] = txn
        return index

    def _count_amounts_in_window(
        self,
        transactions: List[Transaction],
        reference_date: date,
    ) -> Dict[int, int]:
        """Count occurrences of each amount within uniqueness window."""
        window_start = reference_date - timedelta(days=self.uniqueness_window)
        window_end = reference_date + timedelta(days=self.buffer_days + self.uniqueness_window)

        counts = defaultdict(int)
        for txn in transactions:
            if txn.transaction_date is None:
                continue
            if window_start <= txn.transaction_date <= window_end:
                counts[txn.amount_cents] += 1

        return counts

    def _try_reference_match(
        self,
        invoice: Transaction,
        payment_index: Dict[str, Transaction],
        matched_ids: Set[str],
    ) -> Optional[CandidateMatch]:
        """Try to match by exact reference/ID."""
        refs_to_try = []
        if invoice.external_id:
            refs_to_try.append(invoice.external_id.lower())
        if invoice.reference:
            refs_to_try.append(invoice.reference.lower())

        for ref in refs_to_try:
            if ref in payment_index:
                payment = payment_index[ref]
                if payment.id not in matched_ids:
                    # Verify amount matches
                    if payment.amount_cents == invoice.amount_cents:
                        return CandidateMatch(
                            invoice=invoice,
                            payment=payment,
                            amount_match=True,
                            reference_match=True,
                            text_similarity=1.0,
                            days_apart=self._days_between(invoice, payment),
                            is_unique_amount=False,  # Doesn't matter for ref match
                        )

        return None

    def _try_unique_amount_match(
        self,
        invoice: Transaction,
        payment_index: Dict[int, List[Transaction]],
        amount_counts: Dict[int, int],
        matched_ids: Set[str],
        reference_date: date,
    ) -> Optional[CandidateMatch]:
        """
        Try to match by unique amount with orthogonal validation.

        Per V9.3 spec: Requires text similarity confirmation.
        """
        amount = invoice.amount_cents

        # Check if amount is unique in window
        if amount_counts.get(amount, 0) != 2:  # Should be exactly 2 (1 invoice + 1 payment)
            return None

        # Get candidate payments
        candidates = payment_index.get(amount, [])
        candidates = [c for c in candidates if c.id not in matched_ids]

        if len(candidates) != 1:
            return None

        payment = candidates[0]

        # Orthogonal validation: require text similarity
        text_sim = self._calculate_text_similarity(invoice, payment)
        if text_sim < self.text_threshold:
            logger.debug(
                "Amount match rejected - low text similarity",
                invoice_id=invoice.id,
                payment_id=payment.id,
                similarity=text_sim,
            )
            return None

        return CandidateMatch(
            invoice=invoice,
            payment=payment,
            amount_match=True,
            reference_match=False,
            text_similarity=text_sim,
            days_apart=self._days_between(invoice, payment),
            is_unique_amount=True,
        )

    def _calculate_text_similarity(
        self,
        invoice: Transaction,
        payment: Transaction,
    ) -> float:
        """
        Calculate text similarity between transactions.
        Uses multiple fields for robust comparison.
        """
        scores = []

        # Compare counterparty names
        if invoice.counterparty_name and payment.counterparty_name:
            score = fuzz.token_sort_ratio(
                invoice.counterparty_name.lower(),
                payment.counterparty_name.lower(),
            ) / 100.0
            scores.append(score)

        # Compare descriptions
        if invoice.description and payment.description:
            score = fuzz.token_set_ratio(
                invoice.description.lower(),
                payment.description.lower(),
            ) / 100.0
            scores.append(score)

        # Compare RFC if available
        if invoice.counterparty_rfc and payment.counterparty_rfc:
            if invoice.counterparty_rfc.upper() == payment.counterparty_rfc.upper():
                scores.append(1.0)
            else:
                scores.append(0.0)

        if not scores:
            return 0.0

        return sum(scores) / len(scores)

    def _days_between(
        self,
        txn1: Transaction,
        txn2: Transaction,
    ) -> int:
        """Calculate days between two transactions."""
        if txn1.transaction_date is None or txn2.transaction_date is None:
            return 0
        return abs((txn1.transaction_date - txn2.transaction_date).days)

    def _determine_commit_status(
        self,
        invoice: Transaction,
        payment: Transaction,
        reference_date: date,
    ) -> CommitStatus:
        """
        Determine commit status based on transaction dates.

        HARD: Both transactions older than T + hard_threshold
        SOFT: At least one transaction between hard_threshold and T
        SHADOW: Any transaction in buffer zone (T to T + buffer_days)
        """
        hard_cutoff = reference_date + timedelta(days=self.hard_threshold)
        buffer_end = reference_date + timedelta(days=self.buffer_days)

        dates = []
        if invoice.transaction_date:
            dates.append(invoice.transaction_date)
        if payment.transaction_date:
            dates.append(payment.transaction_date)

        if not dates:
            return CommitStatus.SOFT

        latest_date = max(dates)

        if latest_date > reference_date:
            # In buffer zone
            return CommitStatus.SHADOW
        elif latest_date > hard_cutoff:
            # Recent but not in buffer
            return CommitStatus.SOFT
        else:
            # Old enough for hard commit
            return CommitStatus.HARD

    def _build_match_reason(self, match: CandidateMatch) -> str:
        """Build human-readable match reason."""
        reasons = []
        if match.reference_match:
            reasons.append("reference_id_match")
        if match.amount_match:
            reasons.append("exact_amount")
        if match.is_unique_amount:
            reasons.append("unique_in_window")
        if match.text_similarity >= 0.8:
            reasons.append("high_text_similarity")
        return ", ".join(reasons)

    def promote_commits(
        self,
        transactions: List[Transaction],
        new_reference_date: date,
    ) -> List[AuditEntry]:
        """
        Promote commit levels as time passes.

        SHADOW -> SOFT -> HARD
        """
        audit_entries = []

        hard_cutoff = new_reference_date + timedelta(days=self.hard_threshold)

        for txn in transactions:
            if txn.commit_status == CommitStatus.PENDING:
                continue

            if txn.transaction_date is None:
                continue

            old_status = txn.commit_status

            if txn.commit_status == CommitStatus.SHADOW:
                if txn.transaction_date <= new_reference_date:
                    txn.commit_status = CommitStatus.SOFT
            elif txn.commit_status == CommitStatus.SOFT:
                if txn.transaction_date <= hard_cutoff:
                    txn.commit_status = CommitStatus.HARD

            if txn.commit_status != old_status:
                audit_entries.append(AuditEntry(
                    action=AuditAction.MATCH_PROMOTED,
                    transaction_ids=[txn.id],
                    message=f"Commit promoted: {old_status.value} -> {txn.commit_status.value}",
                ))

        return audit_entries
