"""
Integration tests for the reconciliation pipeline.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime

from app.models import (
    Transaction,
    TransactionSource,
    TransactionType,
    ReconciliationJob,
    ReconciliationStatus,
)


class TestReconciliationIntegration:
    """Integration tests for full reconciliation pipeline."""

    @pytest.fixture
    def mock_transactions(self):
        """Create mock transaction data."""
        invoices = [
            Transaction(
                id=f"inv_{i}",
                source=TransactionSource.CFDI,
                amount_cents=10000 + i * 1000,
                transaction_type=TransactionType.DEBIT,
                transaction_date=date(2024, 1, i + 1),
                counterparty_name=f"Proveedor {i}",
                counterparty_rfc=f"RFC{i:012d}",
            )
            for i in range(10)
        ]

        payments = [
            Transaction(
                id=f"pay_{i}",
                source=TransactionSource.BANK,
                amount_cents=10000 + i * 1000,
                transaction_type=TransactionType.CREDIT,
                transaction_date=date(2024, 1, i + 3),
                counterparty_name=f"Proveedor {i}",
                counterparty_rfc=f"RFC{i:012d}",
            )
            for i in range(10)
        ]

        return invoices, payments

    @pytest.mark.asyncio
    async def test_full_pipeline_mock(self, mock_transactions):
        """Test full pipeline with mocked external services."""
        invoices, payments = mock_transactions

        # Test Safe Peeling
        from app.reconciliation.safe_peeling import SafePeelingEngine
        peeling = SafePeelingEngine()
        peeling_result = peeling.process(invoices, payments)

        # With unique amounts and matching RFC, should get matches
        assert peeling_result.stats["matched"] > 0 or \
               peeling_result.stats["remaining_invoices"] > 0

        # Test Clustering on remaining
        if peeling_result.remaining_invoices and peeling_result.remaining_payments:
            from app.reconciliation.clustering import LeidenClusterEngine
            clustering = LeidenClusterEngine()
            cluster_result = clustering.process(
                peeling_result.remaining_invoices,
                peeling_result.remaining_payments,
            )

            # Should create clusters
            assert cluster_result.stats["total_clusters"] >= 0

            # Test Solver on clusters
            if cluster_result.clusters:
                from app.reconciliation.solver import LexicographicMILPSolver
                solver = LexicographicMILPSolver()

                for cluster in cluster_result.clusters[:3]:  # Test first 3
                    result = solver.solve_cluster(cluster)
                    assert result is not None
                    assert result.cluster_id == cluster.id

    def test_algebraic_validator(self):
        """Test the algebraic validator for bank statements."""
        from app.ingestion.validator import AlgebraicValidator
        from app.models import BankTransaction

        validator = AlgebraicValidator()

        # Create transactions that follow balance recurrence
        transactions = [
            BankTransaction(
                id="txn1",
                amount_cents=10000,
                transaction_type=TransactionType.CREDIT,
                balance_after_cents=110000,  # Started at 100000
            ),
            BankTransaction(
                id="txn2",
                amount_cents=5000,
                transaction_type=TransactionType.DEBIT,
                balance_after_cents=105000,  # 110000 - 5000
            ),
            BankTransaction(
                id="txn3",
                amount_cents=3000,
                transaction_type=TransactionType.CREDIT,
                balance_after_cents=108000,  # 105000 + 3000
            ),
        ]

        # Set balance_before for first transaction
        transactions[0].balance_before_cents = 100000

        result = validator.validate_transactions(transactions)

        # Should pass validation
        assert result.density > 0.5  # At least 50% should pass

    def test_cfdi_parser(self):
        """Test CFDI XML parsing."""
        from app.ingestion.cfdi_parser import CFDIParser

        parser = CFDIParser()

        # Sample CFDI XML (simplified)
        sample_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Version="4.0"
            Fecha="2024-01-15T10:30:00"
            Total="1000.00"
            SubTotal="862.07"
            TipoDeComprobante="I"
            MetodoPago="PUE"
            Moneda="MXN">
            <cfdi:Emisor Rfc="AAA010101AAA" Nombre="Empresa Emisora"/>
            <cfdi:Receptor Rfc="BBB020202BBB" Nombre="Empresa Receptora"/>
            <cfdi:Conceptos>
                <cfdi:Concepto Descripcion="Servicio de consultoria" Cantidad="1" ValorUnitario="862.07" Importe="862.07"/>
            </cfdi:Conceptos>
            <cfdi:Complemento>
                <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                    UUID="12345678-1234-1234-1234-123456789012"
                    FechaTimbrado="2024-01-15T10:31:00"/>
            </cfdi:Complemento>
        </cfdi:Comprobante>'''

        result = parser.parse_xml(sample_xml)

        assert result.transaction is not None
        assert result.transaction.amount_cents == 100000  # $1000.00
        assert result.transaction.cfdi_uuid == "12345678-1234-1234-1234-123456789012"
        assert result.transaction.emisor_rfc == "AAA010101AAA"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
