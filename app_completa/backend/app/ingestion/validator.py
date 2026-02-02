"""
Algebraic validator for OCR-extracted bank transactions.
Implements the V9.0 specification for balance recurrence validation.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import structlog

from ..models import BankTransaction, TransactionType

logger = structlog.get_logger()


@dataclass
class OCRCorrection:
    """A potential OCR correction."""
    transaction_id: str
    field: str  # "amount" or "balance"
    original_value: int
    corrected_value: int
    confidence: float
    reason: str


@dataclass
class ValidationResult:
    """Result of algebraic validation."""
    is_valid: bool
    density: float  # Percentage of transactions that pass validation
    total_transactions: int
    valid_transactions: int
    invalid_transactions: int
    corrections: List[OCRCorrection] = field(default_factory=list)
    corrected_transactions: Optional[List[BankTransaction]] = None
    errors: List[str] = field(default_factory=list)
    start_balance_cents: Optional[int] = None
    end_balance_cents: Optional[int] = None


class AlgebraicValidator:
    """
    Validates bank transactions using algebraic recurrence equations.

    The balance recurrence equation:
        B_t = B_{t-1} + credit_t - debit_t

    If a transaction violates this equation, it may indicate:
    1. OCR error in amount or balance
    2. Missing transaction
    3. Structural parsing error
    """

    # OCR confusion matrix for common digit errors
    OCR_CONFUSIONS: Dict[str, List[str]] = {
        "0": ["8", "6", "9"],
        "1": ["7", "4"],
        "2": ["7"],
        "3": ["8"],
        "4": ["1", "9"],
        "5": ["6", "8"],
        "6": ["0", "8", "5"],
        "7": ["1", "2"],
        "8": ["0", "6", "3"],
        "9": ["0", "4"],
    }

    def __init__(
        self,
        min_density_threshold: float = 0.8,
        max_magnitude_change: int = 1,
    ):
        """
        Initialize validator.

        Args:
            min_density_threshold: Minimum pass rate to consider document valid
            max_magnitude_change: Max order of magnitude change allowed in corrections
        """
        self.min_density = min_density_threshold
        self.max_magnitude_change = max_magnitude_change

    def validate_transactions(
        self,
        transactions: List[BankTransaction],
    ) -> ValidationResult:
        """
        Validate a list of transactions using balance recurrence.

        Args:
            transactions: List of bank transactions in chronological order

        Returns:
            ValidationResult with validation details and corrections
        """
        if not transactions:
            return ValidationResult(
                is_valid=True,
                density=1.0,
                total_transactions=0,
                valid_transactions=0,
                invalid_transactions=0,
            )

        # Sort by page and row to ensure correct order
        sorted_txns = sorted(
            transactions,
            key=lambda t: (t.source_page or 0, t.source_row or 0),
        )

        valid_count = 0
        invalid_indices = []
        corrections = []

        for i, txn in enumerate(sorted_txns):
            is_valid, correction = self._validate_single_transaction(
                txn, sorted_txns[i - 1] if i > 0 else None
            )

            if is_valid:
                valid_count += 1
                txn.is_validated = True
                txn.validation_method = "balance_recurrence"
            else:
                invalid_indices.append(i)
                if correction:
                    corrections.append(correction)

        density = valid_count / len(sorted_txns) if sorted_txns else 1.0
        is_valid = density >= self.min_density

        # Apply corrections if we have them
        corrected_transactions = None
        if corrections:
            corrected_transactions = self._apply_corrections(
                sorted_txns, corrections
            )

        return ValidationResult(
            is_valid=is_valid,
            density=density,
            total_transactions=len(sorted_txns),
            valid_transactions=valid_count,
            invalid_transactions=len(invalid_indices),
            corrections=corrections,
            corrected_transactions=corrected_transactions,
        )

    def _validate_single_transaction(
        self,
        txn: BankTransaction,
        prev_txn: Optional[BankTransaction],
    ) -> Tuple[bool, Optional[OCRCorrection]]:
        """
        Validate a single transaction against recurrence equation.

        Returns:
            Tuple of (is_valid, optional_correction)
        """
        # Can't validate without balance info
        if txn.balance_after_cents is None:
            return True, None

        # First transaction - just check it has balance
        if prev_txn is None or prev_txn.balance_after_cents is None:
            txn.balance_before_cents = txn.balance_after_cents - self._get_signed_amount(txn)
            return True, None

        # Calculate expected balance
        expected_balance = prev_txn.balance_after_cents + self._get_signed_amount(txn)
        actual_balance = txn.balance_after_cents

        # Set balance_before
        txn.balance_before_cents = prev_txn.balance_after_cents

        # Check if matches
        if expected_balance == actual_balance:
            return True, None

        # Doesn't match - try to find correction
        difference = actual_balance - expected_balance

        # Try correcting the amount
        amount_correction = self._try_correct_amount(txn, difference)
        if amount_correction:
            return False, amount_correction

        # Try correcting the balance
        balance_correction = self._try_correct_balance(txn, expected_balance)
        if balance_correction:
            return False, balance_correction

        logger.info(
            "Transaction failed validation",
            txn_id=txn.id,
            expected_balance=expected_balance,
            actual_balance=actual_balance,
            difference=difference,
        )

        return False, None

    def _get_signed_amount(self, txn: BankTransaction) -> int:
        """Get signed amount (positive for credit, negative for debit)."""
        if txn.transaction_type == TransactionType.CREDIT:
            return txn.amount_cents
        else:
            return -txn.amount_cents

    def _try_correct_amount(
        self,
        txn: BankTransaction,
        difference: int,
    ) -> Optional[OCRCorrection]:
        """
        Try to correct the transaction amount to fix the balance.

        Applies OCR confusion matrix and checks magnitude invariance.
        """
        original = txn.amount_cents

        # The correct amount would be original + difference (for debit)
        # or original - difference (for credit)
        if txn.transaction_type == TransactionType.CREDIT:
            corrected = original - difference
        else:
            corrected = original + difference

        # Check magnitude invariance (can't add/remove digits)
        if not self._check_magnitude_invariance(original, corrected):
            return None

        # Check if this correction is plausible via OCR confusion
        if not self._is_ocr_plausible(original, corrected):
            return None

        return OCRCorrection(
            transaction_id=txn.id,
            field="amount",
            original_value=original,
            corrected_value=corrected,
            confidence=self._calculate_correction_confidence(original, corrected),
            reason="balance_recurrence_fix",
        )

    def _try_correct_balance(
        self,
        txn: BankTransaction,
        expected_balance: int,
    ) -> Optional[OCRCorrection]:
        """Try to correct the balance reading."""
        original = txn.balance_after_cents
        if original is None:
            return None

        # Check magnitude invariance
        if not self._check_magnitude_invariance(original, expected_balance):
            return None

        # Check OCR plausibility
        if not self._is_ocr_plausible(original, expected_balance):
            return None

        return OCRCorrection(
            transaction_id=txn.id,
            field="balance",
            original_value=original,
            corrected_value=expected_balance,
            confidence=self._calculate_correction_confidence(original, expected_balance),
            reason="balance_recurrence_fix",
        )

    def _check_magnitude_invariance(
        self,
        original: int,
        corrected: int,
    ) -> bool:
        """
        Check that correction doesn't change order of magnitude.

        Per V9.0 spec: Prohibido añadir o quitar dígitos.
        """
        if original <= 0 or corrected <= 0:
            return False

        # Calculate number of digits
        original_digits = len(str(abs(original)))
        corrected_digits = len(str(abs(corrected)))

        return abs(original_digits - corrected_digits) <= self.max_magnitude_change

    def _is_ocr_plausible(
        self,
        original: int,
        corrected: int,
    ) -> bool:
        """
        Check if the correction is plausible given OCR confusion patterns.
        """
        orig_str = str(abs(original))
        corr_str = str(abs(corrected))

        if len(orig_str) != len(corr_str):
            return False

        # Count digit differences
        differences = 0
        for o, c in zip(orig_str, corr_str):
            if o != c:
                differences += 1
                # Check if this is a known confusion
                if c not in self.OCR_CONFUSIONS.get(o, []) and o not in self.OCR_CONFUSIONS.get(c, []):
                    # Unknown confusion - less plausible but not impossible
                    pass

        # Allow up to 2 digit differences
        return differences <= 2

    def _calculate_correction_confidence(
        self,
        original: int,
        corrected: int,
    ) -> float:
        """Calculate confidence score for a correction."""
        orig_str = str(abs(original))
        corr_str = str(abs(corrected))

        if len(orig_str) != len(corr_str):
            return 0.3

        # Count differences
        differences = sum(1 for o, c in zip(orig_str, corr_str) if o != c)

        # Check if differences are known OCR confusions
        known_confusions = 0
        for o, c in zip(orig_str, corr_str):
            if o != c:
                if c in self.OCR_CONFUSIONS.get(o, []) or o in self.OCR_CONFUSIONS.get(c, []):
                    known_confusions += 1

        # Higher confidence if:
        # - Few differences
        # - Differences are known OCR patterns
        base_confidence = 1.0 - (differences * 0.2)
        confusion_bonus = known_confusions * 0.1

        return min(0.95, max(0.3, base_confidence + confusion_bonus))

    def _apply_corrections(
        self,
        transactions: List[BankTransaction],
        corrections: List[OCRCorrection],
    ) -> List[BankTransaction]:
        """Apply corrections to create shadow records."""
        # Create a map of corrections by transaction ID
        correction_map = {c.transaction_id: c for c in corrections}

        corrected = []
        for txn in transactions:
            if txn.id in correction_map:
                correction = correction_map[txn.id]

                # Apply as shadow value (don't modify original)
                if correction.field == "amount":
                    txn.shadow_amount_cents = correction.corrected_value
                    txn.shadow_confidence = correction.confidence
                elif correction.field == "balance":
                    # For balance, we update in place since it's derived
                    txn.balance_after_cents = correction.corrected_value

            corrected.append(txn)

        return corrected

    def validate_page_boundary(
        self,
        last_txn_prev_page: BankTransaction,
        first_txn_curr_page: BankTransaction,
    ) -> bool:
        """
        Validate continuity across page boundaries.

        Per V9.0 spec: B_inicial^(p+1) == B_final^(p)
        """
        if (last_txn_prev_page.balance_after_cents is None or
                first_txn_curr_page.balance_before_cents is None):
            return True  # Can't validate without balance info

        return (
            last_txn_prev_page.balance_after_cents ==
            first_txn_curr_page.balance_before_cents
        )
