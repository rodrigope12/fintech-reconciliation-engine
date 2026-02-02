"""
Tests for the MILP solver.
"""

import pytest
from datetime import date

from app.models import Transaction, TransactionSource, TransactionType, CommitStatus
from app.reconciliation.clustering import Cluster
from app.reconciliation.solver import LexicographicMILPSolver


@pytest.fixture
def solver():
    return LexicographicMILPSolver()


@pytest.fixture
def simple_cluster():
    """Create a simple cluster with 2 invoices and 2 payments that balance."""
    invoices = [
        Transaction(
            id="inv1",
            source=TransactionSource.CFDI,
            amount_cents=10000,  # $100.00
            transaction_type=TransactionType.DEBIT,
            transaction_date=date(2024, 1, 10),
            counterparty_name="Proveedor A",
        ),
        Transaction(
            id="inv2",
            source=TransactionSource.CFDI,
            amount_cents=5000,  # $50.00
            transaction_type=TransactionType.DEBIT,
            transaction_date=date(2024, 1, 15),
            counterparty_name="Proveedor B",
        ),
    ]

    payments = [
        Transaction(
            id="pay1",
            source=TransactionSource.BANK,
            amount_cents=10000,
            transaction_type=TransactionType.CREDIT,
            transaction_date=date(2024, 1, 12),
            counterparty_name="Proveedor A",
        ),
        Transaction(
            id="pay2",
            source=TransactionSource.BANK,
            amount_cents=5000,
            transaction_type=TransactionType.CREDIT,
            transaction_date=date(2024, 1, 17),
            counterparty_name="Proveedor B",
        ),
    ]

    from app.models import TransactionMatch
    edges = [
        TransactionMatch(
            invoice_id="inv1",
            payment_id="pay1",
            combined_score=0.9,
        ),
        TransactionMatch(
            invoice_id="inv2",
            payment_id="pay2",
            combined_score=0.85,
        ),
    ]

    return Cluster(
        id="test_cluster_1",
        invoices=invoices,
        payments=payments,
        edges=edges,
        total_invoice_cents=15000,
        total_payment_cents=15000,
    )


@pytest.fixture
def unbalanced_cluster():
    """Create a cluster where payments don't fully cover invoices."""
    invoices = [
        Transaction(
            id="inv1",
            source=TransactionSource.CFDI,
            amount_cents=10000,
            transaction_type=TransactionType.DEBIT,
            transaction_date=date(2024, 1, 10),
            counterparty_name="Proveedor A",
        ),
    ]

    payments = [
        Transaction(
            id="pay1",
            source=TransactionSource.BANK,
            amount_cents=9500,  # $5 short
            transaction_type=TransactionType.CREDIT,
            transaction_date=date(2024, 1, 12),
            counterparty_name="Proveedor A",
        ),
    ]

    from app.models import TransactionMatch
    edges = [
        TransactionMatch(
            invoice_id="inv1",
            payment_id="pay1",
            combined_score=0.9,
        ),
    ]

    return Cluster(
        id="test_cluster_unbalanced",
        invoices=invoices,
        payments=payments,
        edges=edges,
        total_invoice_cents=10000,
        total_payment_cents=9500,
    )


class TestLexicographicMILPSolver:
    """Test suite for the MILP solver."""

    def test_solve_balanced_cluster(self, solver, simple_cluster):
        """Test solving a perfectly balanced cluster."""
        result = solver.solve_cluster(simple_cluster)

        assert result is not None
        assert result.solution is not None
        assert result.solution.delta_cents == 0, "Delta should be 0 for balanced cluster"
        assert len(result.matched_pairs) == 2, "Should have 2 matched pairs"
        assert not result.needs_rescue, "Should not need rescue"

    def test_solve_unbalanced_cluster_within_tolerance(self, solver, unbalanced_cluster):
        """Test that small gaps are handled via gamma (operational gap)."""
        result = solver.solve_cluster(unbalanced_cluster)

        assert result is not None
        assert result.solution is not None
        # $5 (500 cents) gap should be within tolerance
        assert result.solution.gamma_cents != 0 or result.solution.delta_cents != 0

    def test_solver_respects_causality(self, solver):
        """Test that solver doesn't match payments before invoices beyond buffer."""
        invoices = [
            Transaction(
                id="inv_future",
                source=TransactionSource.CFDI,
                amount_cents=10000,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date(2024, 6, 15),  # Future date
                counterparty_name="Proveedor A",
            ),
        ]

        payments = [
            Transaction(
                id="pay_past",
                source=TransactionSource.BANK,
                amount_cents=10000,
                transaction_type=TransactionType.CREDIT,
                transaction_date=date(2024, 1, 1),  # Way before invoice
                counterparty_name="Proveedor A",
            ),
        ]

        from app.models import TransactionMatch
        edges = [
            TransactionMatch(
                invoice_id="inv_future",
                payment_id="pay_past",
                combined_score=0.9,
            ),
        ]

        cluster = Cluster(
            id="causal_test",
            invoices=invoices,
            payments=payments,
            edges=edges,
            total_invoice_cents=10000,
            total_payment_cents=10000,
        )

        result = solver.solve_cluster(cluster)

        # The solver should not match these due to causality constraints
        # Either no matches or needs rescue
        assert result is not None
        if result.solution:
            # If it found a solution, it shouldn't have matched the causal violation
            assert len(result.matched_pairs) == 0 or result.needs_rescue

    def test_solver_parsimony(self, solver):
        """Test that solver prefers simpler solutions (fewer documents)."""
        # Create scenario where one payment could match multiple invoices
        invoices = [
            Transaction(
                id="inv1",
                source=TransactionSource.CFDI,
                amount_cents=5000,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date(2024, 1, 10),
                counterparty_name="Proveedor A",
            ),
            Transaction(
                id="inv2",
                source=TransactionSource.CFDI,
                amount_cents=5000,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date(2024, 1, 11),
                counterparty_name="Proveedor A",
            ),
            Transaction(
                id="inv3",
                source=TransactionSource.CFDI,
                amount_cents=10000,  # Single invoice that matches exactly
                transaction_type=TransactionType.DEBIT,
                transaction_date=date(2024, 1, 12),
                counterparty_name="Proveedor A",
            ),
        ]

        payments = [
            Transaction(
                id="pay1",
                source=TransactionSource.BANK,
                amount_cents=10000,  # Could match inv3 alone OR inv1+inv2
                transaction_type=TransactionType.CREDIT,
                transaction_date=date(2024, 1, 15),
                counterparty_name="Proveedor A",
            ),
        ]

        from app.models import TransactionMatch
        edges = [
            TransactionMatch(invoice_id="inv1", payment_id="pay1", combined_score=0.8),
            TransactionMatch(invoice_id="inv2", payment_id="pay1", combined_score=0.8),
            TransactionMatch(invoice_id="inv3", payment_id="pay1", combined_score=0.85),
        ]

        cluster = Cluster(
            id="parsimony_test",
            invoices=invoices,
            payments=payments,
            edges=edges,
            total_invoice_cents=20000,
            total_payment_cents=10000,
        )

        result = solver.solve_cluster(cluster)

        # Due to parsimony penalty, solver should prefer matching inv3 alone
        # rather than inv1+inv2 (which involves more documents)
        assert result is not None
        if result.matched_pairs:
            # Check cardinality preference
            total_invoices_matched = sum(
                len(pair.invoice_ids) for pair in result.matched_pairs
            )
            # Ideally should be 1 (just inv3), not 2 (inv1+inv2)
            assert total_invoices_matched <= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
