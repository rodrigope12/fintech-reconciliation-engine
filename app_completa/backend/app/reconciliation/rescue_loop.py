"""
Rescue Loop Engine - Phase 3 of the reconciliation pipeline.

Handles cases where the solver produces delta > 0 by attempting
to merge adjacent clusters and re-solve.

Implements intelligent triggering based on:
- MetodoPago (PPD = partial expected)
- Semantic score threshold
- Orphan amount matching
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
import structlog

from ..config import get_settings
from ..models import (
    Transaction,
    MetodoPago,
    AuditEntry,
    AuditAction,
    AmbiguousCase,
)
from .clustering import Cluster, LeidenClusterEngine
from .solver import LexicographicMILPSolver, SolverResult

logger = structlog.get_logger()


@dataclass
class RescueResult:
    """Result of rescue loop."""
    solver_results: List[SolverResult]
    manual_review: List[AmbiguousCase]
    audit_entries: List[AuditEntry]
    rescue_iterations: int
    hard_stopped: bool


class RescueLoopEngine:
    """
    Phase 3: Rescue Loop for unresolved clusters.

    Trigger conditions:
    1. delta > 0 AND total_remainder == 0 (real error, not partial)
    2. delta matches an orphan amount nearby
    3. Semantic score below threshold

    NOT triggered if:
    - MetodoPago == PPD (partial payment expected)
    - High semantic score (confident match)

    Actions:
    1. Identify adjacent clusters
    2. Merge and re-solve
    3. Hard-stop if merged cluster > N_max
    4. Route to manual review if still unresolved
    """

    def __init__(self):
        self.settings = get_settings()
        self.hard_stop_size = self.settings.hard_stop_cluster_size
        self.semantic_threshold = self.settings.rescue_semantic_threshold
        self.solver = LexicographicMILPSolver()
        self.cluster_engine = LeidenClusterEngine()

    def process(
        self,
        failed_results: List[SolverResult],
        all_clusters: List[Cluster],
        orphan_invoices: List[Transaction],
        orphan_payments: List[Transaction],
    ) -> RescueResult:
        """
        Execute rescue loop on failed solver results.

        Args:
            failed_results: SolverResults that need rescue
            all_clusters: All clusters for adjacency detection
            orphan_invoices: Invoices not in any cluster
            orphan_payments: Payments not in any cluster

        Returns:
            RescueResult with new solutions and manual review items
        """
        logger.info(
            "Starting rescue loop",
            failed_clusters=len(failed_results),
            orphan_invoices=len(orphan_invoices),
            orphan_payments=len(orphan_payments),
        )

        audit_entries = []
        resolved_results = []
        manual_review = []
        iterations = 0
        hard_stopped = False

        # Build cluster map
        cluster_map = {c.id: c for c in all_clusters}

        # Build orphan amount sets
        orphan_inv_amounts = {inv.amount_cents: inv for inv in orphan_invoices}
        orphan_pay_amounts = {pay.amount_cents: pay for pay in orphan_payments}

        for result in failed_results:
            if not result.needs_rescue:
                resolved_results.append(result)
                continue

            # Check if rescue should be triggered
            should_rescue, reason = self._should_trigger_rescue(
                result,
                cluster_map.get(result.cluster_id),
                orphan_inv_amounts,
                orphan_pay_amounts,
            )

            if not should_rescue:
                logger.debug(
                    "Skipping rescue",
                    cluster_id=result.cluster_id,
                    reason=reason,
                )
                resolved_results.append(result)
                continue

            audit_entries.append(AuditEntry(
                action=AuditAction.RESCUE_TRIGGERED,
                cluster_id=result.cluster_id,
                message=f"Rescue triggered: {reason}",
                details={
                    "delta": result.solution.delta_cents if result.solution else 0,
                    "reason": reason,
                },
            ))

            # Attempt rescue
            rescue_result, rescue_audits, was_hard_stopped = self._attempt_rescue(
                result,
                cluster_map,
                orphan_invoices,
                orphan_payments,
            )

            audit_entries.extend(rescue_audits)
            iterations += 1

            if was_hard_stopped:
                hard_stopped = True

            if rescue_result:
                resolved_results.append(rescue_result)
            else:
                # Route to manual review
                case = self._create_manual_review_case(result, cluster_map.get(result.cluster_id))
                manual_review.append(case)

                audit_entries.append(AuditEntry(
                    action=AuditAction.MANUAL_REVIEW_REQUIRED,
                    cluster_id=result.cluster_id,
                    message="Rescue failed, routing to manual review",
                ))

        logger.info(
            "Rescue loop complete",
            iterations=iterations,
            resolved=len(resolved_results),
            manual_review=len(manual_review),
            hard_stopped=hard_stopped,
        )

        return RescueResult(
            solver_results=resolved_results,
            manual_review=manual_review,
            audit_entries=audit_entries,
            rescue_iterations=iterations,
            hard_stopped=hard_stopped,
        )

    def _should_trigger_rescue(
        self,
        result: SolverResult,
        cluster: Optional[Cluster],
        orphan_inv_amounts: Dict[int, Transaction],
        orphan_pay_amounts: Dict[int, Transaction],
    ) -> Tuple[bool, str]:
        """
        Determine if rescue should be triggered.

        Returns:
            Tuple of (should_trigger, reason)
        """
        if not result.solution:
            return True, "no_solution"

        delta = result.solution.delta_cents
        total_remainder = sum(result.solution.remainders.values())
        avg_score = result.solution.semantic_score / max(len(result.solution.matches), 1)

        # Check 1: Is this likely a partial payment (not an error)?
        if cluster:
            ppd_invoices = sum(
                1 for inv in cluster.invoices
                if inv.metodo_pago == MetodoPago.PPD
            )
            if ppd_invoices > 0 and total_remainder > 0:
                return False, "partial_payment_expected"

        # Check 2: High semantic score means confident match
        if avg_score > self.semantic_threshold:
            return False, "high_confidence_match"

        # Check 3: Delta > 0 with no remainder = real error
        if delta > 0 and total_remainder == 0:
            return True, "unbalanced_error"

        # Check 4: Delta matches orphan amount (missing transaction?)
        if delta > 0:
            if delta in orphan_inv_amounts:
                return True, "delta_matches_orphan_invoice"
            if delta in orphan_pay_amounts:
                return True, "delta_matches_orphan_payment"

        return False, "no_rescue_needed"

    def _attempt_rescue(
        self,
        result: SolverResult,
        cluster_map: Dict[str, Cluster],
        orphan_invoices: List[Transaction],
        orphan_payments: List[Transaction],
    ) -> Tuple[Optional[SolverResult], List[AuditEntry], bool]:
        """
        Attempt to rescue a failed result by merging with adjacent data.

        Returns:
            Tuple of (new_result, audit_entries, was_hard_stopped)
        """
        audit_entries = []
        cluster = cluster_map.get(result.cluster_id)

        if not cluster:
            return None, audit_entries, False

        delta = result.solution.delta_cents if result.solution else 0

        # Strategy 1: Add orphan that matches delta
        augmented_cluster = self._try_add_matching_orphan(
            cluster, delta, orphan_invoices, orphan_payments
        )

        if augmented_cluster and augmented_cluster.size <= self.hard_stop_size:
            audit_entries.append(AuditEntry(
                action=AuditAction.RESCUE_TRIGGERED,
                cluster_id=cluster.id,
                message="Added matching orphan to cluster",
            ))

            new_result = self.solver.solve_cluster(augmented_cluster)

            if not new_result.needs_rescue:
                return new_result, audit_entries, False

        # Strategy 2: Find and merge with adjacent cluster
        adjacent_clusters = self._find_adjacent_clusters(cluster, cluster_map)

        for adj_cluster in adjacent_clusters:
            merged = self.cluster_engine.merge_clusters(cluster, adj_cluster)

            if merged.size > self.hard_stop_size:
                audit_entries.append(AuditEntry(
                    action=AuditAction.RESCUE_TRIGGERED,
                    cluster_id=cluster.id,
                    message=f"Hard stop: merged cluster too large ({merged.size})",
                ))
                return None, audit_entries, True

            audit_entries.append(AuditEntry(
                action=AuditAction.RESCUE_TRIGGERED,
                cluster_id=cluster.id,
                message=f"Merging with adjacent cluster {adj_cluster.id}",
            ))

            new_result = self.solver.solve_cluster(merged)

            if not new_result.needs_rescue:
                return new_result, audit_entries, False

        return None, audit_entries, False

    def _try_add_matching_orphan(
        self,
        cluster: Cluster,
        delta: int,
        orphan_invoices: List[Transaction],
        orphan_payments: List[Transaction],
    ) -> Optional[Cluster]:
        """Try to add an orphan that matches the delta amount."""
        # Look for matching invoice
        for inv in orphan_invoices:
            if abs(inv.amount_cents - delta) <= 10:  # Within 10 cents
                return Cluster(
                    id=f"{cluster.id}_aug",
                    invoices=cluster.invoices + [inv],
                    payments=cluster.payments,
                    edges=cluster.edges,
                    total_invoice_cents=cluster.total_invoice_cents + inv.amount_cents,
                    total_payment_cents=cluster.total_payment_cents,
                )

        # Look for matching payment
        for pay in orphan_payments:
            if abs(pay.amount_cents - delta) <= 10:
                return Cluster(
                    id=f"{cluster.id}_aug",
                    invoices=cluster.invoices,
                    payments=cluster.payments + [pay],
                    edges=cluster.edges,
                    total_invoice_cents=cluster.total_invoice_cents,
                    total_payment_cents=cluster.total_payment_cents + pay.amount_cents,
                )

        return None

    def _find_adjacent_clusters(
        self,
        cluster: Cluster,
        cluster_map: Dict[str, Cluster],
    ) -> List[Cluster]:
        """
        Find clusters that are adjacent (share counterparties or similar dates).
        """
        adjacent = []

        # Get counterparty RFCs from this cluster
        cluster_rfcs = set()
        for inv in cluster.invoices:
            if inv.counterparty_rfc:
                cluster_rfcs.add(inv.counterparty_rfc.upper())
        for pay in cluster.payments:
            if pay.counterparty_rfc:
                cluster_rfcs.add(pay.counterparty_rfc.upper())

        # Find clusters with overlapping counterparties
        for other_id, other_cluster in cluster_map.items():
            if other_id == cluster.id:
                continue

            other_rfcs = set()
            for inv in other_cluster.invoices:
                if inv.counterparty_rfc:
                    other_rfcs.add(inv.counterparty_rfc.upper())
            for pay in other_cluster.payments:
                if pay.counterparty_rfc:
                    other_rfcs.add(pay.counterparty_rfc.upper())

            if cluster_rfcs & other_rfcs:
                adjacent.append(other_cluster)

        # Sort by size (prefer smaller clusters)
        adjacent.sort(key=lambda c: c.size)

        return adjacent[:3]  # Limit to top 3

    def _create_manual_review_case(
        self,
        result: SolverResult,
        cluster: Optional[Cluster],
    ) -> AmbiguousCase:
        """Create a manual review case for unresolved cluster."""
        invoice_ids = [inv.id for inv in cluster.invoices] if cluster else result.unmatched_invoices
        payment_ids = [pay.id for pay in cluster.payments] if cluster else result.unmatched_payments

        return AmbiguousCase(
            invoice_ids=invoice_ids,
            payment_ids=payment_ids,
            reason="Rescue loop failed to resolve balance discrepancy",
            solver_delta_cents=result.solution.delta_cents if result.solution else 0,
            best_score=result.solution.semantic_score if result.solution else 0,
        )
