"""
Tests for Safe Peeling Engine.
"""

import pytest
from datetime import date, timedelta

from app.models import Transaction, TransactionSource, TransactionType, CommitStatus
from app.reconciliation.safe_peeling import SafePeelingEngine


@pytest.fixture
def peeling_engine():
    return SafePeelingEngine()


class TestSafePeelingEngine:
    """Test suite for Safe Peeling."""

    def test_exact_reference_match(self, peeling_engine):
        """Test matching by exact reference ID."""
        invoices = [
            Transaction(
                id="inv1",
                external_id="REF-001",
                source=TransactionSource.CFDI,
                amount_cents=10000,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today() - timedelta(days=5),
                counterparty_name="Proveedor A",
            ),
        ]

        payments = [
            Transaction(
                id="pay1",
                external_id="REF-001",  # Same reference
                source=TransactionSource.BANK,
                amount_cents=10000,
                transaction_type=TransactionType.CREDIT,
                transaction_date=date.today() - timedelta(days=3),
                counterparty_name="Proveedor A",
            ),
        ]

        result = peeling_engine.process(invoices, payments)

        assert len(result.matched_pairs) == 1
        assert result.matched_pairs[0].invoice_ids == ["inv1"]
        assert result.matched_pairs[0].payment_ids == ["pay1"]
        assert len(result.remaining_invoices) == 0
        assert len(result.remaining_payments) == 0

    def test_unique_amount_match_with_text_validation(self, peeling_engine):
        """Test matching by unique amount with text similarity validation."""
        invoices = [
            Transaction(
                id="inv1",
                source=TransactionSource.CFDI,
                amount_cents=12345,  # Unique amount
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today() - timedelta(days=5),
                counterparty_name="Empresa XYZ SA",
                description="Compra de materiales",
            ),
        ]

        payments = [
            Transaction(
                id="pay1",
                source=TransactionSource.BANK,
                amount_cents=12345,  # Same unique amount
                transaction_type=TransactionType.CREDIT,
                transaction_date=date.today() - timedelta(days=3),
                counterparty_name="Empresa XYZ",  # Similar name
                description="Pago materiales",
            ),
        ]

        result = peeling_engine.process(invoices, payments)

        # Should match because amount is unique AND text is similar
        assert len(result.matched_pairs) == 1

    def test_no_match_without_text_validation(self, peeling_engine):
        """Test that unique amount alone doesn't create match without text similarity."""
        invoices = [
            Transaction(
                id="inv1",
                source=TransactionSource.CFDI,
                amount_cents=12345,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today() - timedelta(days=5),
                counterparty_name="Empresa ABC",
                description="Servicio A",
            ),
        ]

        payments = [
            Transaction(
                id="pay1",
                source=TransactionSource.BANK,
                amount_cents=12345,
                transaction_type=TransactionType.CREDIT,
                transaction_date=date.today() - timedelta(days=3),
                counterparty_name="Proveedor Diferente",  # Different name
                description="Otro concepto",
            ),
        ]

        result = peeling_engine.process(invoices, payments)

        # Should NOT match because text similarity is low
        assert len(result.matched_pairs) == 0
        assert len(result.remaining_invoices) == 1
        assert len(result.remaining_payments) == 1

    def test_no_greedy_theft(self, peeling_engine):
        """Test that ambiguous amounts don't get matched (anti-greedy-theft)."""
        # Two invoices with same amount, one payment
        invoices = [
            Transaction(
                id="inv1",
                source=TransactionSource.CFDI,
                amount_cents=10000,  # Same amount
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today() - timedelta(days=5),
                counterparty_name="Proveedor A",
            ),
            Transaction(
                id="inv2",
                source=TransactionSource.CFDI,
                amount_cents=10000,  # Same amount
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today() - timedelta(days=4),
                counterparty_name="Proveedor B",
            ),
        ]

        payments = [
            Transaction(
                id="pay1",
                source=TransactionSource.BANK,
                amount_cents=10000,
                transaction_type=TransactionType.CREDIT,
                transaction_date=date.today() - timedelta(days=3),
                counterparty_name="Proveedor A",
            ),
        ]

        result = peeling_engine.process(invoices, payments)

        # Should NOT match because amount is not unique (ambiguous)
        # This prevents "greedy theft"
        assert len(result.matched_pairs) == 0
        assert len(result.remaining_invoices) == 2
        assert len(result.remaining_payments) == 1

    def test_commit_status_assignment(self, peeling_engine):
        """Test correct assignment of commit status based on date."""
        today = date.today()

        invoices = [
            Transaction(
                id="inv_old",
                external_id="REF-OLD",
                source=TransactionSource.CFDI,
                amount_cents=10000,
                transaction_date=today - timedelta(days=10),  # Old -> HARD
            ),
            Transaction(
                id="inv_recent",
                external_id="REF-RECENT",
                source=TransactionSource.CFDI,
                amount_cents=20000,
                transaction_date=today - timedelta(days=1),  # Recent -> SOFT
            ),
            Transaction(
                id="inv_future",
                external_id="REF-FUTURE",
                source=TransactionSource.CFDI,
                amount_cents=30000,
                transaction_date=today + timedelta(days=2),  # Buffer -> SHADOW
            ),
        ]

        payments = [
            Transaction(
                id="pay_old",
                external_id="REF-OLD",
                source=TransactionSource.BANK,
                amount_cents=10000,
                transaction_date=today - timedelta(days=8),
            ),
            Transaction(
                id="pay_recent",
                external_id="REF-RECENT",
                source=TransactionSource.BANK,
                amount_cents=20000,
                transaction_date=today,
            ),
            Transaction(
                id="pay_future",
                external_id="REF-FUTURE",
                source=TransactionSource.BANK,
                amount_cents=30000,
                transaction_date=today + timedelta(days=3),
            ),
        ]

        result = peeling_engine.process(invoices, payments, today)

        assert len(result.matched_pairs) == 3

        # Find each pair and check commit status
        for pair in result.matched_pairs:
            if "inv_old" in pair.invoice_ids:
                assert pair.commit_status == CommitStatus.HARD
            elif "inv_recent" in pair.invoice_ids:
                assert pair.commit_status == CommitStatus.SOFT
            elif "inv_future" in pair.invoice_ids:
                assert pair.commit_status == CommitStatus.SHADOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
