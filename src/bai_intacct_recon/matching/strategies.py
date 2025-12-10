"""
Matching strategies for transaction reconciliation.
Each strategy implements a specific matching approach.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional
import re

from ..models.transaction import NormalizedTransaction


class MatchingStrategy(ABC):
    """Abstract base class for matching strategies."""

    @abstractmethod
    def find_matches(
        self,
        bank_txn: NormalizedTransaction,
        intacct_candidates: list[NormalizedTransaction],
    ) -> list[NormalizedTransaction]:
        """
        Find matching Intacct transactions for a bank transaction.

        Args:
            bank_txn: Bank transaction to match
            intacct_candidates: List of candidate Intacct transactions

        Returns:
            List of matching Intacct transactions (may be empty)
        """
        pass

    @abstractmethod
    def calculate_match_score(
        self,
        bank_txn: NormalizedTransaction,
        matched_intacct: list[NormalizedTransaction],
    ) -> tuple[float, str]:
        """
        Calculate the confidence score and reason for a match.

        Args:
            bank_txn: Bank transaction
            matched_intacct: Matched Intacct transactions

        Returns:
            Tuple of (score 0.0-1.0, reason string)
        """
        pass


class ExactMatchStrategy(MatchingStrategy):
    """
    Exact match strategy - matches on reference, amount, and date.
    Highest confidence matching tier.
    """

    def find_matches(
        self,
        bank_txn: NormalizedTransaction,
        intacct_candidates: list[NormalizedTransaction],
    ) -> list[NormalizedTransaction]:
        """Find exact matches by reference, amount, and date."""
        if not bank_txn.normalized_reference:
            return []

        matches: list[NormalizedTransaction] = []
        for intacct_txn in intacct_candidates:
            if not intacct_txn.normalized_reference:
                continue

            # Check exact match on all fields
            if (
                bank_txn.normalized_reference == intacct_txn.normalized_reference
                and bank_txn.amount == intacct_txn.amount
                and bank_txn.date == intacct_txn.date
            ):
                matches.append(intacct_txn)

        # Return first match only for exact matching
        return matches[:1] if matches else []

    def calculate_match_score(
        self,
        bank_txn: NormalizedTransaction,
        matched_intacct: list[NormalizedTransaction],
    ) -> tuple[float, str]:
        """Exact matches have perfect score."""
        return 1.0, "Exact match on reference, amount, and date"


class FuzzyDateStrategy(MatchingStrategy):
    """
    Fuzzy date matching - exact reference and amount, date within tolerance.
    """

    def __init__(self, tolerance_days: int = 3):
        """
        Initialize with date tolerance.

        Args:
            tolerance_days: Maximum days difference allowed
        """
        self.tolerance_days = tolerance_days

    def find_matches(
        self,
        bank_txn: NormalizedTransaction,
        intacct_candidates: list[NormalizedTransaction],
    ) -> list[NormalizedTransaction]:
        """Find matches with date tolerance."""
        if not bank_txn.normalized_reference:
            return []

        matches: list[NormalizedTransaction] = []
        for intacct_txn in intacct_candidates:
            if not intacct_txn.normalized_reference:
                continue

            # Check reference and amount match exactly
            if (
                bank_txn.normalized_reference == intacct_txn.normalized_reference
                and bank_txn.amount == intacct_txn.amount
            ):
                # Check date within tolerance
                date_diff = abs((bank_txn.date - intacct_txn.date).days)
                if date_diff <= self.tolerance_days:
                    matches.append(intacct_txn)

        # Return closest date match
        if matches:
            matches.sort(key=lambda t: abs((bank_txn.date - t.date).days))
            return matches[:1]
        return []

    def calculate_match_score(
        self,
        bank_txn: NormalizedTransaction,
        matched_intacct: list[NormalizedTransaction],
    ) -> tuple[float, str]:
        """Score based on date proximity."""
        if not matched_intacct:
            return 0.0, "No match"

        intacct_txn = matched_intacct[0]
        date_diff = abs((bank_txn.date - intacct_txn.date).days)

        # Score decreases with date difference
        score = max(0.8, 1.0 - (date_diff * 0.05))
        reason = f"Reference and amount match, {date_diff} day(s) date difference"

        return score, reason


class AmountToleranceStrategy(MatchingStrategy):
    """
    Amount tolerance matching - allows small differences in amounts.
    """

    def __init__(
        self,
        date_tolerance_days: int = 5,
        amount_tolerance: Decimal = Decimal("10.00"),
        percent_tolerance: float = 1.0,
    ):
        """
        Initialize with tolerances.

        Args:
            date_tolerance_days: Maximum days difference
            amount_tolerance: Maximum absolute amount difference
            percent_tolerance: Maximum percentage difference
        """
        self.date_tolerance_days = date_tolerance_days
        self.amount_tolerance = amount_tolerance
        self.percent_tolerance = percent_tolerance

    def find_matches(
        self,
        bank_txn: NormalizedTransaction,
        intacct_candidates: list[NormalizedTransaction],
    ) -> list[NormalizedTransaction]:
        """Find matches with amount tolerance."""
        if not bank_txn.normalized_reference:
            return []

        matches: list[NormalizedTransaction] = []
        for intacct_txn in intacct_candidates:
            if not intacct_txn.normalized_reference:
                continue

            # Check reference matches exactly
            if bank_txn.normalized_reference != intacct_txn.normalized_reference:
                continue

            # Check date within tolerance
            date_diff = abs((bank_txn.date - intacct_txn.date).days)
            if date_diff > self.date_tolerance_days:
                continue

            # Check amount within tolerance
            amount_diff = abs(bank_txn.amount - intacct_txn.amount)

            # Check absolute tolerance
            if amount_diff <= self.amount_tolerance:
                matches.append(intacct_txn)
                continue

            # Check percentage tolerance
            if bank_txn.amount > 0:
                percent_diff = (amount_diff / bank_txn.amount) * 100
                if percent_diff <= self.percent_tolerance:
                    matches.append(intacct_txn)

        return matches[:1] if matches else []

    def calculate_match_score(
        self,
        bank_txn: NormalizedTransaction,
        matched_intacct: list[NormalizedTransaction],
    ) -> tuple[float, str]:
        """Score based on amount variance."""
        if not matched_intacct:
            return 0.0, "No match"

        intacct_txn = matched_intacct[0]
        amount_diff = abs(bank_txn.amount - intacct_txn.amount)
        date_diff = abs((bank_txn.date - intacct_txn.date).days)

        # Base score
        score = 0.75

        # Adjust for amount variance
        if bank_txn.amount > 0:
            percent_diff = float(amount_diff / bank_txn.amount) * 100
            score -= min(0.2, percent_diff / 10)

        reason = (
            f"Reference match with ${amount_diff:.2f} amount variance, "
            f"{date_diff} day(s) date difference"
        )

        return score, reason


class FuzzyDescriptionStrategy(MatchingStrategy):
    """
    Fuzzy description matching - uses text similarity.
    Lowest confidence tier, used as fallback.
    """

    def __init__(
        self, similarity_threshold: float = 0.85, date_tolerance_days: int = 7
    ):
        """
        Initialize with similarity threshold.

        Args:
            similarity_threshold: Minimum similarity ratio (0.0-1.0)
            date_tolerance_days: Maximum days difference
        """
        self.similarity_threshold = similarity_threshold
        self.date_tolerance_days = date_tolerance_days

    def find_matches(
        self,
        bank_txn: NormalizedTransaction,
        intacct_candidates: list[NormalizedTransaction],
    ) -> list[NormalizedTransaction]:
        """Find matches based on description similarity."""
        if not bank_txn.description:
            return []

        bank_desc = self._normalize_description(bank_txn.description)

        best_match: Optional[NormalizedTransaction] = None
        best_score = 0.0

        for intacct_txn in intacct_candidates:
            # Amount must match exactly for description matching
            if bank_txn.amount != intacct_txn.amount:
                continue

            # Check date within tolerance
            date_diff = abs((bank_txn.date - intacct_txn.date).days)
            if date_diff > self.date_tolerance_days:
                continue

            if not intacct_txn.description:
                continue

            intacct_desc = self._normalize_description(intacct_txn.description)

            # Calculate similarity
            similarity = SequenceMatcher(None, bank_desc, intacct_desc).ratio()

            if similarity >= self.similarity_threshold and similarity > best_score:
                best_match = intacct_txn
                best_score = similarity

        return [best_match] if best_match else []

    def _normalize_description(self, description: str) -> str:
        """Normalize description for comparison."""
        # Convert to lowercase
        desc = description.lower()
        # Remove special characters
        desc = re.sub(r"[^a-z0-9\s]", "", desc)
        # Normalize whitespace
        desc = " ".join(desc.split())
        return desc

    def calculate_match_score(
        self,
        bank_txn: NormalizedTransaction,
        matched_intacct: list[NormalizedTransaction],
    ) -> tuple[float, str]:
        """Score based on description similarity."""
        if not matched_intacct:
            return 0.0, "No match"

        intacct_txn = matched_intacct[0]

        bank_desc = self._normalize_description(bank_txn.description)
        intacct_desc = self._normalize_description(intacct_txn.description)

        similarity = SequenceMatcher(None, bank_desc, intacct_desc).ratio()

        # Lower base score for fuzzy matches
        score = 0.5 + (similarity * 0.3)
        reason = f"Description similarity: {similarity:.1%}"

        return score, reason
