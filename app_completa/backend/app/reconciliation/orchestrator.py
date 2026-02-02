"""
Reconciliation Orchestrator - Main pipeline coordinator.

Orchestrates the full reconciliation pipeline:
1. Ingestion (OCR + Facturama)
2. Safe Peeling (Phase 0)
3. Clustering (Phase 1)
4. MILP Solving (Phase 2)
5. Rescue Loop (Phase 3)
6. Result aggregation
"""

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Callable
import time

import structlog

from ..config import get_settings
from ..models import (
    Transaction,
    ReconciliationJob,
    ReconciliationResult,
    ReconciliationSummary,
    ReconciliationStatus,
    MatchedPair,
    PartialMatch,
    AuditEntry,
    AuditAction,
    TransactionSource,
)
from ..ingestion import BankStatementParser, CFDIParser
from ..integrations import FacturamaClient
from ..utils.text_similarity import TextSimilarityEngine
from .safe_peeling import SafePeelingEngine
from .clustering import LeidenClusterEngine
from .solver import LexicographicMILPSolver
from .rescue_loop import RescueLoopEngine

logger = structlog.get_logger()


class ReconciliationOrchestrator:
    """
    Main orchestrator for the reconciliation pipeline.

    Coordinates all phases and manages progress reporting.
    """

    def __init__(self):
        self.settings = get_settings()
        self.bank_parser = BankStatementParser()
        self.cfdi_parser = CFDIParser()
        self.similarity_engine = TextSimilarityEngine()
        self.peeling_engine = SafePeelingEngine()
        self.cluster_engine = LeidenClusterEngine()
        self.solver = LexicographicMILPSolver()
        self.rescue_engine = RescueLoopEngine()

    async def run(
        self,
        job: ReconciliationJob,
        facturama_password: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> ReconciliationResult:
        """
        Execute the full reconciliation pipeline.

        Args:
            job: ReconciliationJob with input parameters
            facturama_password: Facturama API password
            progress_callback: Optional callback for progress updates

        Returns:
            ReconciliationResult with all matches and audit trail
        """
        start_time = time.time()
        result = ReconciliationResult(job_id=job.id)

        def update_progress(percent: float, phase: str):
            job.progress = percent
            job.current_phase = phase
            if progress_callback:
                progress_callback(percent, phase)

        try:
            job.status = ReconciliationStatus.PROCESSING
            job.started_at = datetime.utcnow()

            # Phase: Ingestion
            update_progress(5, "Ingesting bank statements")
            job.status = ReconciliationStatus.INGESTING

            bank_transactions = await self._ingest_bank_statements(job.bank_files)
            result.audit_log.append(AuditEntry(
                action=AuditAction.TRANSACTION_INGESTED,
                message=f"Ingested {len(bank_transactions)} bank transactions",
            ))

            update_progress(15, "Downloading CFDIs from Facturama")

            cfdi_transactions = await self._ingest_cfdis(
                job.rfc, facturama_password, job.start_date, job.end_date
            )
            result.audit_log.append(AuditEntry(
                action=AuditAction.TRANSACTION_INGESTED,
                message=f"Ingested {len(cfdi_transactions)} CFDIs",
            ))

            update_progress(25, "Computing text embeddings")

            # Compute embeddings for similarity
            all_transactions = bank_transactions + cfdi_transactions
            await self._compute_embeddings(all_transactions)

            # Separate invoices and payments
            invoices = [t for t in all_transactions if t.source == TransactionSource.CFDI]
            payments = [t for t in all_transactions if t.source == TransactionSource.BANK]

            # Phase 0: Safe Peeling
            update_progress(35, "Safe Peeling (Phase 0)")
            job.status = ReconciliationStatus.PEELING

            peeling_result = self.peeling_engine.process(
                invoices, payments, date.today()
            )

            result.matched_pairs.extend(peeling_result.matched_pairs)
            result.audit_log.extend(peeling_result.audit_entries)

            remaining_invoices = peeling_result.remaining_invoices
            remaining_payments = peeling_result.remaining_payments

            update_progress(45, f"Safe Peeling complete: {len(peeling_result.matched_pairs)} matches")

            # Phase 1: Clustering
            update_progress(50, "Clustering (Phase 1)")
            job.status = ReconciliationStatus.CLUSTERING

            clustering_result = self.cluster_engine.process(
                remaining_invoices, remaining_payments
            )

            result.audit_log.extend(clustering_result.audit_entries)

            update_progress(60, f"Created {len(clustering_result.clusters)} clusters")

            # Phase 2: MILP Solving
            update_progress(65, "Solving clusters (Phase 2)")
            job.status = ReconciliationStatus.SOLVING

            solver_results = []
            failed_results = []
            total_clusters = len(clustering_result.clusters)

            for i, cluster in enumerate(clustering_result.clusters):
                progress = 65 + (25 * (i + 1) / total_clusters)
                update_progress(progress, f"Solving cluster {i + 1}/{total_clusters}")

                solver_result = self.solver.solve_cluster(cluster)
                result.audit_log.extend(solver_result.audit_entries)

                if solver_result.needs_rescue:
                    failed_results.append(solver_result)
                else:
                    solver_results.append(solver_result)
                    result.matched_pairs.extend(solver_result.matched_pairs)
                    result.partial_matches.extend(solver_result.partial_matches)

            # Phase 3: Rescue Loop
            if failed_results:
                update_progress(90, f"Rescue Loop (Phase 3): {len(failed_results)} clusters")
                job.status = ReconciliationStatus.RESCUE

                rescue_result = self.rescue_engine.process(
                    failed_results,
                    clustering_result.clusters,
                    clustering_result.orphan_invoices,
                    clustering_result.orphan_payments,
                )

                result.audit_log.extend(rescue_result.audit_entries)
                result.manual_review.extend(rescue_result.manual_review)

                for sr in rescue_result.solver_results:
                    result.matched_pairs.extend(sr.matched_pairs)
                    result.partial_matches.extend(sr.partial_matches)

            # Collect unmatched
            matched_invoice_ids = set()
            matched_payment_ids = set()

            for pair in result.matched_pairs:
                matched_invoice_ids.update(pair.invoice_ids)
                matched_payment_ids.update(pair.payment_ids)

            for partial in result.partial_matches:
                matched_invoice_ids.add(partial.invoice_id)
                matched_payment_ids.update(partial.payment_ids)

            result.unmatched_invoices = [
                inv.id for inv in invoices if inv.id not in matched_invoice_ids
            ]
            result.unmatched_payments = [
                pay.id for pay in payments if pay.id not in matched_payment_ids
            ]

            # Compute summary
            update_progress(95, "Computing summary")
            result.summary = self._compute_summary(
                result, invoices, payments, time.time() - start_time
            )

            # Complete
            update_progress(100, "Complete")
            job.status = ReconciliationStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            result.status = ReconciliationStatus.COMPLETED
            result.completed_at = datetime.utcnow()

        except Exception as e:
            logger.exception("Reconciliation failed", error=str(e))
            job.status = ReconciliationStatus.FAILED
            result.status = ReconciliationStatus.FAILED
            result.errors.append(str(e))

        return result

    async def _ingest_bank_statements(
        self,
        pdf_paths: List[str],
    ) -> List[Transaction]:
        """Ingest bank statement PDFs."""
        transactions = []

        for pdf_path in pdf_paths:
            try:
                parse_result = await self.bank_parser.parse_pdf(pdf_path)
                transactions.extend(parse_result.transactions)

                if parse_result.errors:
                    logger.warning(
                        "Bank parsing errors",
                        path=pdf_path,
                        errors=parse_result.errors,
                    )

            except Exception as e:
                logger.error(
                    "Failed to parse bank statement",
                    path=pdf_path,
                    error=str(e),
                )

        return transactions

    async def _ingest_cfdis(
        self,
        rfc: str,
        password: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ) -> List[Transaction]:
        """Download and parse CFDIs from Facturama."""
        transactions = []

        client = FacturamaClient(user=rfc, password=password)

        try:
            # Validate credentials
            if not await client.validate_credentials():
                raise ValueError("Invalid Facturama credentials")

            # Download CFDIs
            cfdis = await client.download_all_cfdis(
                start_date=start_date.date() if start_date else None,
                end_date=end_date.date() if end_date else None,
            )

            # Parse each CFDI
            for cfdi_data in cfdis:
                xml_content = cfdi_data["xml"]
                parse_result = self.cfdi_parser.parse_xml(xml_content)

                if parse_result.transaction:
                    transactions.append(parse_result.transaction)

                if parse_result.errors:
                    logger.warning(
                        "CFDI parsing errors",
                        uuid=cfdi_data["metadata"].uuid,
                        errors=parse_result.errors,
                    )

        finally:
            await client.close()

        return transactions

    async def _compute_embeddings(
        self,
        transactions: List[Transaction],
    ) -> None:
        """Compute text embeddings for all transactions."""
        texts = []
        for txn in transactions:
            text_parts = []
            if txn.counterparty_name:
                text_parts.append(txn.counterparty_name)
            if txn.description:
                text_parts.append(txn.description)
            if txn.reference:
                text_parts.append(txn.reference)
            texts.append(" ".join(text_parts))

        embeddings = await self.similarity_engine.encode_batch(texts)

        for txn, embedding in zip(transactions, embeddings):
            txn.embedding = embedding

    def _compute_summary(
        self,
        result: ReconciliationResult,
        invoices: List[Transaction],
        payments: List[Transaction],
        processing_time: float,
    ) -> ReconciliationSummary:
        """Compute summary statistics."""
        matched_invoice_ids = set()
        matched_payment_ids = set()
        partial_invoice_ids = set()

        for pair in result.matched_pairs:
            matched_invoice_ids.update(pair.invoice_ids)
            matched_payment_ids.update(pair.payment_ids)

        for partial in result.partial_matches:
            partial_invoice_ids.add(partial.invoice_id)
            matched_payment_ids.update(partial.payment_ids)

        matched_amount = sum(
            pair.total_invoice_cents for pair in result.matched_pairs
        )
        total_gap = sum(pair.gap_cents for pair in result.matched_pairs)
        remainder_amount = sum(
            partial.remainder_cents for partial in result.partial_matches
        )

        return ReconciliationSummary(
            total_invoices=len(invoices),
            total_payments=len(payments),
            matched_invoices=len(matched_invoice_ids),
            matched_payments=len(matched_payment_ids),
            partial_invoices=len(partial_invoice_ids),
            unmatched_invoices=len(result.unmatched_invoices),
            unmatched_payments=len(result.unmatched_payments),
            manual_review_count=len(result.manual_review),
            total_invoice_amount_cents=sum(inv.amount_cents for inv in invoices),
            total_payment_amount_cents=sum(pay.amount_cents for pay in payments),
            matched_amount_cents=matched_amount,
            unmatched_invoice_amount_cents=sum(
                inv.amount_cents for inv in invoices
                if inv.id in result.unmatched_invoices
            ),
            unmatched_payment_amount_cents=sum(
                pay.amount_cents for pay in payments
                if pay.id in result.unmatched_payments
            ),
            remainder_amount_cents=remainder_amount,
            total_gap_cents=total_gap,
            processing_time_seconds=processing_time,
            clusters_processed=len(result.cluster_results),
        )
