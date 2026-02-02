
from typing import List, Optional
import structlog
from .domain import TransactionBlock, ValidationContext, IsomorphicVariant

logger = structlog.get_logger()

class CSPSolver:
    """
    Solves the Global Constraint Satisfaction Problem:
    Find a selection of variants x_i for each block i such that:
    Start + Sum(Credit_i - Debit_i) = End
    """

    def __init__(self, tolerance_cents: int = 1):
        self.tolerance_cents = tolerance_cents
        self.best_solution: Optional[List[TransactionBlock]] = None

    def solve(self, context: ValidationContext, blocks: List[TransactionBlock]) -> bool:
        """
        Entry point to solve the document.
        Modifies 'blocks' in-place with selected variants if successful.
        """
        logger.info("Starting V16 CSP Solver", 
                    blocks=len(blocks), 
                    target_delta=context.end_balance_cents - context.start_balance_cents)
        
        target_delta = context.end_balance_cents - context.start_balance_cents
        
        # Precompute maximum possible value change remaining for pruning
        # This is a heuristic: max(debit, credit) for each block
        max_remaining_changes = [0] * (len(blocks) + 1)
        for i in range(len(blocks) - 1, -1, -1):
            block_max = 0
            # Max possible delta from this block
            # Candidate debits (negative delta)
            for variants in blocks[i].debit_candidates:
                for v in variants:
                    block_max = max(block_max, abs(v.value_cents))
            # Candidate credits (positive delta)
            for variants in blocks[i].credit_candidates:
                for v in variants:
                    block_max = max(block_max, abs(v.value_cents))
            
            max_remaining_changes[i] = max_remaining_changes[i+1] + block_max

        result = self._recursive_solve(
            blocks, 0, 0, target_delta, max_remaining_changes
        )
        
        if result:
            logger.info("Solution found!")
            return True
        else:
            logger.warning("No solution found matching global balance.")
            return False

    def _recursive_solve(self, 
                         blocks: List[TransactionBlock], 
                         index: int, 
                         current_delta: int, 
                         target_delta: int,
                         max_remaining_changes: List[int]) -> bool:
        
        # Base case: All blocks processed
        if index == len(blocks):
            return abs(current_delta - target_delta) <= self.tolerance_cents

        # Pruning: Is it impossible to reach target?
        # If current_delta is too far from target_delta compared to max possible change remaining
        if abs(target_delta - current_delta) > max_remaining_changes[index] + self.tolerance_cents:
            # We can't possibly make up the difference
            return False

        block = blocks[index]

        # Strategy: Prioritize INCLUSION over EXCLUSION to maximize transaction count.
        # Try to use the block as a transaction first. Only skip if impossible.

        # Option 1: Used as DEBIT
        # Iterate over all debit candidate groups
        for variants_group in block.debit_candidates:
            for variant in variants_group:
                # Apply -value
                new_delta = current_delta - variant.value_cents
                if self._recursive_solve(blocks, index + 1, new_delta, target_delta, max_remaining_changes):
                    block.selected_debit = variant
                    block.selected_credit = None
                    return True

        # Option 2: Used as CREDIT
        for variants_group in block.credit_candidates:
            for variant in variants_group:
                # Apply +value
                new_delta = current_delta + variant.value_cents
                if self._recursive_solve(blocks, index + 1, new_delta, target_delta, max_remaining_changes):
                    block.selected_debit = None
                    block.selected_credit = variant
                    return True

        # Option 0: Null Hypothesis (This block is noise/text-only)
        # Only if we failed to use it as a transaction
        if self._recursive_solve(blocks, index + 1, current_delta, target_delta, max_remaining_changes):
            # If solution found down this path, this block is indeed noise
            block.selected_debit = None
            block.selected_credit = None
            return True

        # Backtrack
        return False
