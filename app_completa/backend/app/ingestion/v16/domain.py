
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

@dataclass
class IsomorphicVariant:
    """
    Represents a single hypothesis for a numeric token's value.
    Example: Raw 'l00' -> Variant(100.00, method='fix_l_to_1')
    """
    value_cents: int
    confidence: float
    transformation_method: str
    original_text: str

@dataclass
class TransactionBlock:
    """
    A vertical slice of the document anchored by a Date.
    Contains all potential debit/credit tokens found in that vertical zone.
    """
    block_id: int
    anchor_date: date
    # Candidates for Debit amount (e.g. from column 3, 4, etc.)
    debit_candidates: List[List[IsomorphicVariant]] = field(default_factory=list)
    # Candidates for Credit amount
    credit_candidates: List[List[IsomorphicVariant]] = field(default_factory=list)
    # Description text pieces found in this block
    description_lines: List[str] = field(default_factory=list)
    
    # Selected solution (filled by Solver)
    selected_debit: Optional[IsomorphicVariant] = None
    selected_credit: Optional[IsomorphicVariant] = None

@dataclass
class ValidationContext:
    """
    Global boundary conditions for the CSP Solver.
    """
    start_balance_cents: int
    end_balance_cents: int
    
    # Helper to track running sum during recursion
    current_calculated_balance: int = 0
