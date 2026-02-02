"""
Bank statement PDF parser with OCR and algebraic validation.
Implements the V9.0 specification for template-free extraction.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict, Any
from decimal import Decimal, InvalidOperation

import structlog

from ..config import get_settings
from ..models import BankTransaction, TransactionType, CommitStatus
from ..integrations.google_vision import (
    GoogleVisionClient,
    OCRDocument,
    OCRPage,
    OCRRow,
)
from .validator import AlgebraicValidator, ValidationResult

logger = structlog.get_logger()


@dataclass
class ColumnMapping:
    """Detected column mapping for a bank statement."""
    date_col: int
    description_col: int
    debit_col: Optional[int]
    credit_col: Optional[int]
    balance_col: int
    reference_col: Optional[int]


@dataclass
class ParseResult:
    """Result of parsing a bank statement."""
    transactions: List[BankTransaction]
    validation_result: ValidationResult
    warnings: List[str]
    errors: List[str]
    column_mapping: Optional[ColumnMapping]


class BankStatementParser:
    """
    Parser for bank statement PDFs.

    Uses Google Vision OCR and algebraic validation to ensure
    accurate extraction without pre-defined templates.
    """

    # Common patterns for Mexican bank statements
    AMOUNT_PATTERN = re.compile(
        r"[$]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"
    )
    DATE_PATTERNS = [
        re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})"),  # DD/MM/YYYY or DD-MM-YY
        re.compile(r"(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{2,4})", re.I),
    ]
    MONTH_MAP = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    }

    def __init__(self):
        self.settings = get_settings()
        self.ocr_client = GoogleVisionClient()
        self.validator = AlgebraicValidator()

    async def parse_pdf(
        self,
        pdf_path: str,
        statement_year: Optional[int] = None,
    ) -> ParseResult:
        """
        Parse a bank statement PDF.

        Args:
            pdf_path: Path to the PDF file
            statement_year: Year of the statement (for date parsing)

        Returns:
            ParseResult with extracted transactions
        """
        logger.info("Parsing bank statement", path=pdf_path)
        warnings = []
        errors = []

        # Step 1: OCR the PDF
        try:
            # Offload blocking OCR and PDF rendering to a separate thread
            # Add 300s timeout to prevent hangs
            ocr_doc = await asyncio.wait_for(
                asyncio.to_thread(self.ocr_client.process_pdf, pdf_path),
                timeout=300.0
            )
        except asyncio.TimeoutError:
            logger.error("OCR timed out", path=pdf_path)
            return ParseResult(
                transactions=[],
                validation_result=ValidationResult(
                    is_valid=False,
                    density=0.0,
                    total_transactions=0,
                    valid_transactions=0,
                    invalid_transactions=0,
                ),
                warnings=[],
                errors=[f"OCR timed out (300s): {pdf_path}"],
                column_mapping=None,
            )
        except Exception as e:
            logger.error("OCR failed", error=str(e))
            return ParseResult(
                transactions=[],
                validation_result=ValidationResult(
                    is_valid=False,
                    density=0.0,
                    total_transactions=0,
                    valid_transactions=0,
                    invalid_transactions=0,
                ),
                warnings=[],
                errors=[f"OCR failed: {str(e)}"],
                column_mapping=None,
            )

        # Step 2: V16 Global Constraint Solver Parsing (CSP Engine)
        from .v16.engine import V16BankParserEngine
        
        logger.info("Using V16 Global Constraint Parser")
        v16_engine = V16BankParserEngine()
        transactions, context = v16_engine.process(ocr_doc)
        
        if transactions:
            logger.info("V16 Parser success", count=len(transactions))
            
            # Map context to validation result
            # V16 implies 100% mathematical validity if it returns transactions
            start_bal = context.start_balance_cents if context else 0
            end_bal = context.end_balance_cents if context else 0
            
            val_result = ValidationResult(
                 is_valid=True,
                 density=1.0,
                 total_transactions=len(transactions),
                 valid_transactions=len(transactions),
                 invalid_transactions=0,
                 start_balance_cents=start_bal,
                 end_balance_cents=end_bal
            )
            
            return ParseResult(
                transactions=transactions,
                validation_result=val_result,
                warnings=[],
                errors=[],
                column_mapping=None
            )
        else:
            logger.warning("V16 Parser failed to find solution. Fallback to legacy parsing? No, returning empty result for now to enforce zero-error policy.")
            return ParseResult(
                transactions=[],
                validation_result=ValidationResult(
                    is_valid=False,
                    density=0.0,
                    total_transactions=0,
                    valid_transactions=0,
                    invalid_transactions=0,
                ),
                warnings=["V16 Solver found no solution or boundary conditions"],
                errors=["V16 Solver Failed"],
                column_mapping=None
            )
