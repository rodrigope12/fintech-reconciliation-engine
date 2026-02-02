"""
Lexicographic MILP Solver - Phase 2 of the reconciliation pipeline.

Implements the V9.3 specification with:
- Tripartite residual model (delta, remainder, gamma)
- Causality temporal constraints
- Parsimony penalty (Occam's Razor)
- 3-phase lexicographic optimization

Uses PuLP with HiGHS solver for Python 3.12 compatibility.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Dict, Optional, Tuple
import time
import os
import sys

import structlog
import pulp

from ..config import get_settings
from ..models import (
    Transaction,
    TransactionMatch,
    CommitStatus,
    MatchConfidence,
    MetodoPago,
    MatchedPair,
    PartialMatch,
    AuditEntry,
    AuditAction,
    SolverPhase,
)
from .clustering import Cluster

logger = structlog.get_logger()


@dataclass
class SolverSolution:
    """Solution from MILP solver."""
    # Selected transactions
    selected_invoices: List[str] = field(default_factory=list)
    selected_payments: List[str] = field(default_factory=list)

    # Matched pairs (invoice_id -> payment_id)
    matches: Dict[str, str] = field(default_factory=dict)

    # Remainders (invoice_id -> cents)
    remainders: Dict[str, int] = field(default_factory=dict)

    # Residuals
    delta_cents: int = 0  # Technical error
    gamma_cents: int = 0  # Operational gap

    # Quality metrics
    semantic_score: float = 0.0
    cardinality: int = 0

    # Solver stats
    status: str = "unknown"
    solve_time_ms: int = 0
    phase1_value: float = 0.0
    phase2_value: float = 0.0
    phase3_value: float = 0.0


@dataclass
class SolverResult:
    """Complete result from solving a cluster."""
    cluster_id: str
    solution: Optional[SolverSolution]
    matched_pairs: List[MatchedPair] = field(default_factory=list)
    partial_matches: List[PartialMatch] = field(default_factory=list)
    unmatched_invoices: List[str] = field(default_factory=list)
    unmatched_payments: List[str] = field(default_factory=list)
    audit_entries: List[AuditEntry] = field(default_factory=list)
    needs_rescue: bool = False


class LexicographicMILPSolver:
    """
    3-Phase Lexicographic MILP Solver using HiGHS via PuLP.

    Phase 1: Minimize (delta + |gamma|) - Financial integrity
    Phase 2: Minimize cardinality - Parsimony (Occam's Razor)
    Phase 3: Maximize semantic score - Quality refinement

    All amounts are in CENTS (integers) for exact arithmetic.
    """

    def __init__(self):
        self.settings = get_settings()
        self.timeout = self.settings.solver_timeout_seconds
        self.causality_buffer = self.settings.causality_buffer_days

        # Configure Gurobi License
        self._setup_gurobi_license()

    def _setup_gurobi_license(self):
        """Set up Gurobi license from bundled file or local path."""
        # 1. Check if running in PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            license_path = os.path.join(sys._MEIPASS, 'gurobi.lic')
        else:
            # 2. Check local path (dev mode)
            # Assuming current working directory or specific path
            license_path = os.path.join(os.getcwd(), 'gurobi.lic')
            # Fallback to the known user path if not in CWD
            if not os.path.exists(license_path):
                license_path = "/Users/rodrigoperezcordero/Documents/conciliacion/app_completa/gurobi.lic"

        if os.path.exists(license_path):
            logger.info("Found Gurobi license", path=license_path)
            os.environ["GRB_LICENSE_FILE"] = license_path
        else:
            logger.warning("Gurobi license not found", path=license_path)

    def solve_cluster(
        self,
        cluster: Cluster,
    ) -> SolverResult:
        """
        Solve a cluster using 3-phase lexicographic optimization.

        Args:
            cluster: Cluster to solve

        Returns:
            SolverResult with matches and metrics
        """
        start_time = time.time()
        logger.info(
            "Solving cluster",
            cluster_id=cluster.id,
            invoices=len(cluster.invoices),
            payments=len(cluster.payments),
        )

        audit_entries = []

        # Calculate dynamic delta cap
        total_payment_cents = sum(p.amount_cents for p in cluster.payments)
        max_delta = self.settings.calculate_allowed_delta(total_payment_cents)

        # Build data structures
        inv_map = {inv.id: inv for inv in cluster.invoices}
        pay_map = {pay.id: pay for pay in cluster.payments}
        edge_weights = {(e.invoice_id, e.payment_id): e.combined_score for e in cluster.edges}

        # Phase 1: Minimize error
        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_STARTED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_1_MINIMIZE_ERROR,
        ))

        phase1_result = self._solve_phase1(
            cluster, inv_map, pay_map, edge_weights, max_delta
        )

        if phase1_result is None:
            logger.warning("Phase 1 failed", cluster_id=cluster.id)
            return SolverResult(
                cluster_id=cluster.id,
                solution=None,
                unmatched_invoices=[inv.id for inv in cluster.invoices],
                unmatched_payments=[pay.id for pay in cluster.payments],
                needs_rescue=True,
            )

        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_PHASE_COMPLETED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_1_MINIMIZE_ERROR,
            details={"delta": phase1_result["delta"], "gamma": phase1_result["gamma"]},
        ))

        # Phase 2: Minimize cardinality (given phase 1 constraints)
        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_STARTED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_2_MINIMIZE_CARDINALITY,
        ))

        phase2_result = self._solve_phase2(
            cluster, inv_map, pay_map, edge_weights, max_delta,
            phase1_result["delta"], phase1_result["gamma"]
        )

        if phase2_result is None:
            # Use phase 1 result
            phase2_result = phase1_result

        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_PHASE_COMPLETED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_2_MINIMIZE_CARDINALITY,
            details={"cardinality": phase2_result.get("cardinality", 0)},
        ))

        # Phase 3: Maximize semantic score (given phase 1 and 2 constraints)
        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_STARTED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_3_MAXIMIZE_SCORE,
        ))

        solution = self._solve_phase3(
            cluster, inv_map, pay_map, edge_weights, max_delta,
            phase1_result["delta"], phase1_result["gamma"],
            phase2_result.get("cardinality")
        )

        if solution is None:
            solution = self._extract_solution_from_phase2(phase2_result, cluster)

        solution.solve_time_ms = int((time.time() - start_time) * 1000)
        solution.phase1_value = phase1_result["delta"] + abs(phase1_result["gamma"])
        solution.phase2_value = phase2_result.get("cardinality", 0)

        audit_entries.append(AuditEntry(
            action=AuditAction.SOLVER_PHASE_COMPLETED,
            cluster_id=cluster.id,
            solver_phase=SolverPhase.PHASE_3_MAXIMIZE_SCORE,
            details={"score": solution.semantic_score},
        ))

        # Convert solution to result
        result = self._solution_to_result(
            cluster.id, solution, inv_map, pay_map, audit_entries
        )

        # Check if rescue is needed
        result.needs_rescue = (
            solution.delta_cents > 0 and
            sum(solution.remainders.values()) == 0 and
            solution.semantic_score < self.settings.rescue_semantic_threshold
        )

        logger.info(
            "Cluster solved",
            cluster_id=cluster.id,
            delta=solution.delta_cents,
            gamma=solution.gamma_cents,
            matches=len(solution.matches),
            time_ms=solution.solve_time_ms,
        )

        return result

    def _solve_phase1(
        self,
        cluster: Cluster,
        inv_map: Dict[str, Transaction],
        pay_map: Dict[str, Transaction],
        edge_weights: Dict[Tuple[str, str], float],
        max_delta: int,
    ) -> Optional[Dict]:
        """
        Phase 1: Minimize delta + |gamma| (financial integrity).
        """
        prob = pulp.LpProblem("Phase1_MinError", pulp.LpMinimize)

        # Variables
        x = {inv_id: pulp.LpVariable(f"x_{inv_id}", cat=pulp.LpBinary)
             for inv_id in inv_map}
        y = {pay_id: pulp.LpVariable(f"y_{pay_id}", cat=pulp.LpBinary)
             for pay_id in pay_map}

        # Remainder variables (for partial payments)
        r = {inv_id: pulp.LpVariable(f"r_{inv_id}", lowBound=0,
                                      upBound=inv_map[inv_id].amount_cents, cat=pulp.LpInteger)
             for inv_id in inv_map}

        # Gamma (operational gap) - can be positive or negative
        gamma_pos = pulp.LpVariable("gamma_pos", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)
        gamma_neg = pulp.LpVariable("gamma_neg", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)

        # Delta (technical error) - always non-negative
        delta = pulp.LpVariable("delta", lowBound=0, upBound=max_delta, cat=pulp.LpInteger)

        # Balance constraint: invoices - remainders = payments + gamma + delta
        sum_inv = pulp.lpSum(x[i] * inv_map[i].amount_cents - r[i] for i in inv_map)
        sum_pay = pulp.lpSum(y[j] * pay_map[j].amount_cents for j in pay_map)
        prob += sum_inv - sum_pay + gamma_pos - gamma_neg + delta == 0, "balance"

        # Remainder constraints: r_i <= x_i * amount_i
        for inv_id, inv in inv_map.items():
            prob += r[inv_id] <= x[inv_id] * inv.amount_cents, f"rem_bound_{inv_id}"

        # Causality constraints: payment date >= invoice date - buffer
        for inv_id, inv in inv_map.items():
            for pay_id, pay in pay_map.items():
                if inv.transaction_date and pay.transaction_date:
                    min_date = inv.transaction_date - timedelta(days=self.causality_buffer)
                    if pay.transaction_date < min_date:
                        # This pair is causally invalid
                        prob += x[inv_id] + y[pay_id] <= 1, f"causal_{inv_id}_{pay_id}"

        # Objective: Minimize delta + |gamma|
        prob += delta + gamma_pos + gamma_neg

        # Solve with Gurobi
        # msg=0 disables log output to stdout
        solver = pulp.GUROBI(msg=0, timeLimit=self.timeout // 3)
        try:
            prob.solve(solver)
        except Exception as e:
            logger.error("Gurobi solver failed", error=str(e))
            # Fallback (though likely won't work well if Gurobi failed due to license)
            # or simply let it fail to be caught by the check below

        if prob.status not in (pulp.LpStatusOptimal, pulp.LpStatusNotSolved):
            return None

        return {
            "delta": int(pulp.value(delta)) if pulp.value(delta) else 0,
            "gamma": int(pulp.value(gamma_pos) - pulp.value(gamma_neg)) if pulp.value(gamma_pos) else 0,
            "x": {k: int(pulp.value(v)) for k, v in x.items() if pulp.value(v)},
            "y": {k: int(pulp.value(v)) for k, v in y.items() if pulp.value(v)},
            "r": {k: int(pulp.value(v)) for k, v in r.items() if pulp.value(v)},
        }

    def _solve_phase2(
        self,
        cluster: Cluster,
        inv_map: Dict[str, Transaction],
        pay_map: Dict[str, Transaction],
        edge_weights: Dict[Tuple[str, str], float],
        max_delta: int,
        fixed_delta: int,
        fixed_gamma: int,
    ) -> Optional[Dict]:
        """
        Phase 2: Minimize cardinality (parsimony), given phase 1 bounds.
        """
        prob = pulp.LpProblem("Phase2_MinCardinality", pulp.LpMinimize)

        # Variables
        x = {inv_id: pulp.LpVariable(f"x_{inv_id}", cat=pulp.LpBinary)
             for inv_id in inv_map}
        y = {pay_id: pulp.LpVariable(f"y_{pay_id}", cat=pulp.LpBinary)
             for pay_id in pay_map}

        r = {inv_id: pulp.LpVariable(f"r_{inv_id}", lowBound=0,
                                      upBound=inv_map[inv_id].amount_cents, cat=pulp.LpInteger)
             for inv_id in inv_map}

        gamma_pos = pulp.LpVariable("gamma_pos", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)
        gamma_neg = pulp.LpVariable("gamma_neg", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)

        delta = pulp.LpVariable("delta", lowBound=0, upBound=max_delta, cat=pulp.LpInteger)

        # Balance constraint
        sum_inv = pulp.lpSum(x[i] * inv_map[i].amount_cents - r[i] for i in inv_map)
        sum_pay = pulp.lpSum(y[j] * pay_map[j].amount_cents for j in pay_map)
        prob += sum_inv - sum_pay + gamma_pos - gamma_neg + delta == 0, "balance"

        # Remainder bounds
        for inv_id, inv in inv_map.items():
            prob += r[inv_id] <= x[inv_id] * inv.amount_cents, f"rem_bound_{inv_id}"

        # Causality constraints
        for inv_id, inv in inv_map.items():
            for pay_id, pay in pay_map.items():
                if inv.transaction_date and pay.transaction_date:
                    min_date = inv.transaction_date - timedelta(days=self.causality_buffer)
                    if pay.transaction_date < min_date:
                        prob += x[inv_id] + y[pay_id] <= 1, f"causal_{inv_id}_{pay_id}"

        # Phase 1 constraint: maintain optimal error level
        prob += delta + gamma_pos + gamma_neg <= fixed_delta + abs(fixed_gamma) + 1, "phase1_bound"

        # Objective: Minimize cardinality (number of selected invoices)
        prob += pulp.lpSum(x.values())

        # Solve with Gurobi
        solver = pulp.GUROBI(msg=0, timeLimit=self.timeout // 3)
        try:
            prob.solve(solver)
        except Exception as e:
            logger.error("Gurobi solver failed in Phase 2", error=str(e))

        if prob.status not in (pulp.LpStatusOptimal, pulp.LpStatusNotSolved):
            return None

        return {
            "delta": int(pulp.value(delta)) if pulp.value(delta) else 0,
            "gamma": int(pulp.value(gamma_pos) - pulp.value(gamma_neg)) if pulp.value(gamma_pos) else 0,
            "cardinality": sum(1 for v in x.values() if pulp.value(v) and pulp.value(v) > 0.5),
            "x": {k: int(pulp.value(v)) for k, v in x.items() if pulp.value(v)},
            "y": {k: int(pulp.value(v)) for k, v in y.items() if pulp.value(v)},
            "r": {k: int(pulp.value(v)) for k, v in r.items() if pulp.value(v)},
        }

    def _solve_phase3(
        self,
        cluster: Cluster,
        inv_map: Dict[str, Transaction],
        pay_map: Dict[str, Transaction],
        edge_weights: Dict[Tuple[str, str], float],
        max_delta: int,
        fixed_delta: int,
        fixed_gamma: int,
        max_cardinality: Optional[int],
    ) -> Optional[SolverSolution]:
        """
        Phase 3: Maximize semantic score, given phase 1 and 2 bounds.
        """
        prob = pulp.LpProblem("Phase3_MaxScore", pulp.LpMaximize)

        # Variables
        x = {inv_id: pulp.LpVariable(f"x_{inv_id}", cat=pulp.LpBinary)
             for inv_id in inv_map}
        y = {pay_id: pulp.LpVariable(f"y_{pay_id}", cat=pulp.LpBinary)
             for pay_id in pay_map}

        # Matching variables z_ij (explicit pair selection)
        z = {}
        for (inv_id, pay_id), weight in edge_weights.items():
            z[(inv_id, pay_id)] = pulp.LpVariable(f"z_{inv_id}_{pay_id}", cat=pulp.LpBinary)

        r = {inv_id: pulp.LpVariable(f"r_{inv_id}", lowBound=0,
                                      upBound=inv_map[inv_id].amount_cents, cat=pulp.LpInteger)
             for inv_id in inv_map}

        gamma_pos = pulp.LpVariable("gamma_pos", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)
        gamma_neg = pulp.LpVariable("gamma_neg", lowBound=0,
                                    upBound=self.settings.fixed_gap_threshold_cents, cat=pulp.LpInteger)

        delta = pulp.LpVariable("delta", lowBound=0, upBound=max_delta, cat=pulp.LpInteger)

        # Balance constraint
        sum_inv = pulp.lpSum(x[i] * inv_map[i].amount_cents - r[i] for i in inv_map)
        sum_pay = pulp.lpSum(y[j] * pay_map[j].amount_cents for j in pay_map)
        prob += sum_inv - sum_pay + gamma_pos - gamma_neg + delta == 0, "balance"

        # Remainder bounds
        for inv_id, inv in inv_map.items():
            prob += r[inv_id] <= x[inv_id] * inv.amount_cents, f"rem_bound_{inv_id}"

        # z_ij constraints: z_ij <= x_i and z_ij <= y_j
        for (inv_id, pay_id), z_var in z.items():
            prob += z_var <= x[inv_id], f"z_x_{inv_id}_{pay_id}"
            prob += z_var <= y[pay_id], f"z_y_{inv_id}_{pay_id}"

        # Causality constraints
        for inv_id, inv in inv_map.items():
            for pay_id, pay in pay_map.items():
                if inv.transaction_date and pay.transaction_date:
                    min_date = inv.transaction_date - timedelta(days=self.causality_buffer)
                    if pay.transaction_date < min_date:
                        prob += x[inv_id] + y[pay_id] <= 1, f"causal_{inv_id}_{pay_id}"

        # Phase 1 constraint
        prob += delta + gamma_pos + gamma_neg <= fixed_delta + abs(fixed_gamma) + 1, "phase1_bound"

        # Phase 2 constraint (if available)
        if max_cardinality is not None:
            prob += pulp.lpSum(x.values()) <= max_cardinality + 1, "phase2_bound"

        # Objective: Maximize semantic score
        prob += pulp.lpSum(z[(i, j)] * int(w * 1000) for (i, j), w in edge_weights.items() if (i, j) in z)

        # Solve with Gurobi
        solver = pulp.GUROBI(msg=0, timeLimit=self.timeout // 3)
        try:
            prob.solve(solver)
        except Exception as e:
            logger.error("Gurobi solver failed in Phase 3", error=str(e))

        if prob.status not in (pulp.LpStatusOptimal, pulp.LpStatusNotSolved):
            return None

        # Extract solution
        solution = SolverSolution(
            selected_invoices=[i for i, v in x.items() if pulp.value(v) and pulp.value(v) > 0.5],
            selected_payments=[j for j, v in y.items() if pulp.value(v) and pulp.value(v) > 0.5],
            remainders={i: int(pulp.value(v)) for i, v in r.items() if pulp.value(v) and pulp.value(v) > 0},
            delta_cents=int(pulp.value(delta)) if pulp.value(delta) else 0,
            gamma_cents=int(pulp.value(gamma_pos) - pulp.value(gamma_neg)) if pulp.value(gamma_pos) else 0,
            cardinality=sum(1 for v in x.values() if pulp.value(v) and pulp.value(v) > 0.5),
            status=str(pulp.LpStatus[prob.status]),
        )

        # Build matches from z variables
        for (inv_id, pay_id), z_var in z.items():
            if pulp.value(z_var) and pulp.value(z_var) > 0.5:
                solution.matches[inv_id] = pay_id
                solution.semantic_score += edge_weights.get((inv_id, pay_id), 0)

        solution.phase3_value = solution.semantic_score

        return solution

    def _extract_solution_from_phase2(
        self,
        phase2_result: Dict,
        cluster: Cluster,
    ) -> SolverSolution:
        """Extract SolverSolution from phase 2 result."""
        x = phase2_result.get("x", {})
        y = phase2_result.get("y", {})
        r = phase2_result.get("r", {})

        solution = SolverSolution(
            selected_invoices=[i for i, v in x.items() if v and v > 0.5],
            selected_payments=[j for j, v in y.items() if v and v > 0.5],
            remainders={i: v for i, v in r.items() if v and v > 0},
            delta_cents=phase2_result.get("delta", 0),
            gamma_cents=phase2_result.get("gamma", 0),
            cardinality=phase2_result.get("cardinality", 0),
            status="from_phase2",
        )

        # Simple matching heuristic for phase 2 results
        for edge in cluster.edges:
            if (edge.invoice_id in solution.selected_invoices and
                    edge.payment_id in solution.selected_payments and
                    edge.invoice_id not in solution.matches):
                solution.matches[edge.invoice_id] = edge.payment_id
                solution.semantic_score += edge.combined_score

        return solution

    def _solution_to_result(
        self,
        cluster_id: str,
        solution: SolverSolution,
        inv_map: Dict[str, Transaction],
        pay_map: Dict[str, Transaction],
        audit_entries: List[AuditEntry],
    ) -> SolverResult:
        """Convert SolverSolution to SolverResult with MatchedPairs."""
        matched_pairs = []
        partial_matches = []
        used_invoices = set()
        used_payments = set()

        for inv_id, pay_id in solution.matches.items():
            inv = inv_map.get(inv_id)
            pay = pay_map.get(pay_id)

            if not inv:
                logger.warning("Matched invoice ID not found in map", inv_id=inv_id, cluster_id=cluster_id)
                continue
            if not pay:
                logger.warning("Matched payment ID not found in map", pay_id=pay_id, cluster_id=cluster_id)
                continue

            used_invoices.add(inv_id)
            used_payments.add(pay_id)

            remainder = solution.remainders.get(inv_id, 0)
            
            # Check if remainder fits within allowed gap threshold
            # If so, treat as Full Match with a gap
            effective_gap = solution.gamma_cents
            is_gap_convertible = False
            
            # Use max_abs_delta_cents (from UI "Tolerancia Absoluta") to decide if we accept the gap
            if 0 < remainder <= self.settings.max_abs_delta_cents:
                # Treat remainder as a gap
                effective_gap = remainder
                remainder = 0
                is_gap_convertible = True

            if remainder > 0:
                # Partial match
                partial = PartialMatch(
                    invoice_id=inv_id,
                    payment_ids=[pay_id],
                    invoice_amount_cents=inv.amount_cents,
                    paid_amount_cents=inv.amount_cents - remainder,
                    remainder_cents=remainder,
                    partial_expected=inv.metodo_pago == MetodoPago.PPD,
                    confidence=MatchConfidence.MEDIUM,
                )
                partial_matches.append(partial)
            else:
                # Full match
                pair = MatchedPair(
                    invoice_ids=[inv_id],
                    payment_ids=[pay_id],
                    total_invoice_cents=inv.amount_cents,
                    total_payment_cents=pay.amount_cents,
                    gap_cents=effective_gap,
                    confidence=MatchConfidence.MEDIUM,
                    commit_status=CommitStatus.SOFT,
                    matched_by="milp_solver",
                )
                matched_pairs.append(pair)
        
        logger.info(
            "Solution conversion result",
            cluster_id=cluster_id,
            matches_in_solution=len(solution.matches),
            pairs_created=len(matched_pairs),
            partials_created=len(partial_matches)
        )

        # Identify unmatched
        unmatched_invoices = [
            inv_id for inv_id in inv_map
            if inv_id not in used_invoices
        ]
        unmatched_payments = [
            pay_id for pay_id in pay_map
            if pay_id not in used_payments
        ]

        return SolverResult(
            cluster_id=cluster_id,
            solution=solution,
            matched_pairs=matched_pairs,
            partial_matches=partial_matches,
            unmatched_invoices=unmatched_invoices,
            unmatched_payments=unmatched_payments,
            audit_entries=audit_entries,
        )
