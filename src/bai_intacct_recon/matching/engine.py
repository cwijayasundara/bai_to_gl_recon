"""
Multi-tier matching engine for transaction reconciliation.
Implements configurable matching strategies with priority ordering.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
import fnmatch
import logging

from ..models.transaction import (
    NormalizedTransaction,
    TransactionSource,
    TransactionType,
    MatchResult,
    ReconciliationSummary,
)
from ..config import ReconConfig
from .strategies import (
    MatchingStrategy,
    ExactMatchStrategy,
    FuzzyDateStrategy,
    AmountToleranceStrategy,
    FuzzyDescriptionStrategy,
)

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """
    Main reconciliation engine that orchestrates the matching process.

    Implements a multi-tier matching approach where transactions are
    matched in order of priority/confidence.
    """

    def __init__(self, config: ReconConfig):
        """
        Initialize the reconciliation engine.

        Args:
            config: Application configuration
        """
        self.config = config
        self.strategies = self._build_strategies()

    def _build_strategies(self) -> list[tuple[str, MatchingStrategy]]:
        """
        Build matching strategies from configuration.

        Returns:
            List of (tier_name, strategy) tuples ordered by priority
        """
        strategies: list[tuple[str, MatchingStrategy]] = []

        matching_config = self.config.matching
        tiers = matching_config.tiers if hasattr(matching_config, "tiers") else []

        enabled_tiers = [t for t in tiers if t.enabled]
        sorted_tiers = sorted(enabled_tiers, key=lambda x: x.priority)

        for tier in sorted_tiers:
            tier_name = tier.name
            rules = tier.rules

            # Map tier configuration to strategy
            strategy = self._create_strategy(tier_name, rules)
            if strategy:
                strategies.append((tier_name, strategy))
                logger.debug(f"Loaded matching tier: {tier_name}")

        return strategies

    def _create_strategy(
        self, tier_name: str, rules: list
    ) -> Optional[MatchingStrategy]:
        """
        Create a matching strategy from rule configuration.

        Args:
            tier_name: Name of the matching tier
            rules: List of rule configurations

        Returns:
            Matching strategy or None
        """
        # Find relevant rules
        reference_rule = next(
            (r for r in rules if r.field == "reference"), None
        )
        amount_rule = next((r for r in rules if r.field == "amount"), None)
        date_rule = next((r for r in rules if r.field == "date"), None)
        description_rule = next(
            (r for r in rules if r.field == "description"), None
        )

        # Build strategy based on tier name and rules
        if "exact" in tier_name.lower() and "fuzzy" not in tier_name.lower():
            # Check if all required rules are exact match
            all_exact = all(
                r.match_type == "exact" for r in rules if r.required
            )
            if all_exact:
                return ExactMatchStrategy()

        if date_rule and date_rule.match_type == "tolerance":
            date_tolerance = date_rule.tolerance_days or 3

            if amount_rule and amount_rule.match_type == "tolerance":
                amount_tolerance = Decimal(str(amount_rule.tolerance_amount or 10.0))
                percent_tolerance = amount_rule.tolerance_percent or 1.0
                return AmountToleranceStrategy(
                    date_tolerance_days=date_tolerance,
                    amount_tolerance=amount_tolerance,
                    percent_tolerance=percent_tolerance,
                )
            return FuzzyDateStrategy(tolerance_days=date_tolerance)

        if description_rule and description_rule.match_type == "fuzzy":
            threshold = description_rule.similarity_threshold or 0.85
            date_tolerance = 7
            if date_rule:
                date_tolerance = date_rule.tolerance_days or 7
            return FuzzyDescriptionStrategy(
                similarity_threshold=threshold,
                date_tolerance_days=date_tolerance,
            )

        # Default to exact match
        return ExactMatchStrategy()

    def reconcile(
        self,
        bank_transactions: list[NormalizedTransaction],
        intacct_transactions: list[NormalizedTransaction],
    ) -> tuple[
        list[MatchResult], list[NormalizedTransaction], list[NormalizedTransaction]
    ]:
        """
        Perform reconciliation between bank and Intacct transactions.

        Args:
            bank_transactions: List of bank transactions (BAI2)
            intacct_transactions: List of Intacct transactions

        Returns:
            Tuple of (matched_results, bank_only, intacct_only)
        """
        start_time = datetime.now()
        logger.info(
            f"Starting reconciliation: {len(bank_transactions)} bank txns, "
            f"{len(intacct_transactions)} Intacct txns"
        )

        # Filter out excluded transactions
        bank_txns, bank_excluded = self._filter_exclusions(
            bank_transactions, source="bank"
        )
        intacct_txns, intacct_excluded = self._filter_exclusions(
            intacct_transactions, source="intacct"
        )

        # Track unmatched transactions
        unmatched_bank = {txn.id: txn for txn in bank_txns}
        unmatched_intacct = {txn.id: txn for txn in intacct_txns}

        matches: list[MatchResult] = []

        # Process each tier in priority order
        for tier_name, strategy in self.strategies:
            logger.debug(f"Processing matching tier: {tier_name}")

            # Find matches for this tier
            tier_matches = self._find_tier_matches(
                list(unmatched_bank.values()),
                list(unmatched_intacct.values()),
                strategy,
                tier_name,
            )

            # Remove matched transactions from unmatched pools
            for match in tier_matches:
                if match.bank_transaction.id in unmatched_bank:
                    del unmatched_bank[match.bank_transaction.id]
                    match.bank_transaction.is_matched = True
                    match.bank_transaction.match_tier = tier_name

                for intacct_txn in match.intacct_transactions:
                    if intacct_txn.id in unmatched_intacct:
                        del unmatched_intacct[intacct_txn.id]
                        intacct_txn.is_matched = True
                        intacct_txn.match_tier = tier_name

            matches.extend(tier_matches)

            logger.debug(
                f"Tier {tier_name}: {len(tier_matches)} matches found, "
                f"{len(unmatched_bank)} bank and {len(unmatched_intacct)} "
                f"Intacct remaining"
            )

        # Combine unmatched with excluded
        bank_only = list(unmatched_bank.values()) + bank_excluded
        intacct_only = list(unmatched_intacct.values()) + intacct_excluded

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Reconciliation complete in {elapsed:.2f}s: {len(matches)} matches, "
            f"{len(bank_only)} bank-only, {len(intacct_only)} Intacct-only"
        )

        return matches, bank_only, intacct_only

    def _filter_exclusions(
        self,
        transactions: list[NormalizedTransaction],
        source: str,
    ) -> tuple[list[NormalizedTransaction], list[NormalizedTransaction]]:
        """
        Filter out transactions that should be excluded from matching.

        Args:
            transactions: List of transactions to filter
            source: "bank" or "intacct"

        Returns:
            Tuple of (included, excluded) transactions
        """
        included: list[NormalizedTransaction] = []
        excluded: list[NormalizedTransaction] = []

        exclusions = self.config.exclusions

        for txn in transactions:
            is_excluded = False

            if source == "bank":
                # Check BAI2 type code exclusions
                bank_only_codes = exclusions.bank_only_type_codes or []
                if txn.bai2_type_code in bank_only_codes:
                    is_excluded = True

            elif source == "intacct":
                # Check GL account pattern exclusions
                gl_patterns = exclusions.gl_only_account_patterns or []
                if txn.gl_account:
                    for pattern in gl_patterns:
                        if fnmatch.fnmatch(txn.gl_account, pattern):
                            is_excluded = True
                            break

                # Check reference pattern exclusions
                if not is_excluded and txn.reference:
                    ref_patterns = exclusions.gl_only_reference_patterns or []
                    for pattern in ref_patterns:
                        if fnmatch.fnmatch(txn.reference, pattern):
                            is_excluded = True
                            break

            if is_excluded:
                excluded.append(txn)
            else:
                included.append(txn)

        return included, excluded

    def _find_tier_matches(
        self,
        bank_txns: list[NormalizedTransaction],
        intacct_txns: list[NormalizedTransaction],
        strategy: MatchingStrategy,
        tier_name: str,
    ) -> list[MatchResult]:
        """
        Find matches for a specific matching tier.

        Args:
            bank_txns: Unmatched bank transactions
            intacct_txns: Unmatched Intacct transactions
            strategy: Matching strategy to use
            tier_name: Name of the tier for logging

        Returns:
            List of match results
        """
        matches: list[MatchResult] = []

        # Index Intacct transactions by type for faster lookup
        intacct_by_type: dict[TransactionType, list[NormalizedTransaction]] = {
            TransactionType.CREDIT: [],
            TransactionType.DEBIT: [],
        }
        for txn in intacct_txns:
            intacct_by_type[txn.type].append(txn)

        # Track which Intacct transactions have been matched in this tier
        matched_intacct_ids: set[str] = set()

        for bank_txn in bank_txns:
            # Only match with same transaction type
            candidates = [
                t
                for t in intacct_by_type.get(bank_txn.type, [])
                if t.id not in matched_intacct_ids
            ]

            # Find matching transactions
            matched_intacct = strategy.find_matches(bank_txn, candidates)

            if matched_intacct:
                # Calculate match details
                score, reason = strategy.calculate_match_score(bank_txn, matched_intacct)

                # Calculate variances
                amount_variance: Optional[Decimal] = None
                date_variance: Optional[int] = None

                if len(matched_intacct) == 1:
                    intacct_txn = matched_intacct[0]
                    if bank_txn.amount != intacct_txn.amount:
                        amount_variance = bank_txn.amount - intacct_txn.amount
                    if bank_txn.date != intacct_txn.date:
                        date_variance = abs((bank_txn.date - intacct_txn.date).days)

                match_result = MatchResult(
                    bank_transaction=bank_txn,
                    intacct_transactions=matched_intacct,
                    match_tier=tier_name,
                    match_score=score,
                    match_reason=reason,
                    amount_variance=amount_variance,
                    date_variance_days=date_variance,
                )
                matches.append(match_result)

                # Mark Intacct transactions as matched
                for intacct_txn in matched_intacct:
                    matched_intacct_ids.add(intacct_txn.id)

        return matches

    def generate_summary(
        self,
        bank_transactions: list[NormalizedTransaction],
        intacct_transactions: list[NormalizedTransaction],
        matches: list[MatchResult],
        bank_only: list[NormalizedTransaction],
        intacct_only: list[NormalizedTransaction],
        bai2_filename: str,
        intacct_filename: str,
        processing_time: float,
    ) -> ReconciliationSummary:
        """
        Generate a summary of the reconciliation results.

        Args:
            bank_transactions: All bank transactions
            intacct_transactions: All Intacct transactions
            matches: List of match results
            bank_only: Unmatched bank transactions
            intacct_only: Unmatched Intacct transactions
            bai2_filename: Name of BAI2 file
            intacct_filename: Name of Intacct file
            processing_time: Time taken in seconds

        Returns:
            Reconciliation summary object
        """
        # Calculate totals
        bank_credits = sum(
            t.amount for t in bank_transactions if t.type == TransactionType.CREDIT
        )
        bank_debits = sum(
            t.amount for t in bank_transactions if t.type == TransactionType.DEBIT
        )
        intacct_credits = sum(
            t.amount for t in intacct_transactions if t.type == TransactionType.CREDIT
        )
        intacct_debits = sum(
            t.amount for t in intacct_transactions if t.type == TransactionType.DEBIT
        )

        # Calculate total variance
        total_variance = sum(
            (m.amount_variance for m in matches if m.amount_variance), Decimal("0")
        )

        # Count matches by tier
        tier_counts: dict[str, int] = {}
        for match in matches:
            tier_counts[match.match_tier] = tier_counts.get(match.match_tier, 0) + 1

        # Determine statement period
        all_dates = [t.date for t in bank_transactions]
        period_start = min(all_dates) if all_dates else datetime.now().date()
        period_end = max(all_dates) if all_dates else datetime.now().date()

        # Count variances (matches with amount differences)
        variance_count = sum(1 for m in matches if m.amount_variance)

        return ReconciliationSummary(
            bai2_filename=bai2_filename,
            intacct_filename=intacct_filename,
            reconciliation_date=datetime.now(),
            statement_period_start=period_start,
            statement_period_end=period_end,
            total_bank_transactions=len(bank_transactions),
            total_intacct_transactions=len(intacct_transactions),
            matched_count=len(matches),
            bank_only_count=len(bank_only),
            intacct_only_count=len(intacct_only),
            variance_count=variance_count,
            bank_total_credits=bank_credits,
            bank_total_debits=bank_debits,
            intacct_total_credits=intacct_credits,
            intacct_total_debits=intacct_debits,
            total_amount_variance=total_variance,
            matches_by_tier=tier_counts,
            processing_time_seconds=processing_time,
            config_file_used=self.config.config_file_path,
        )
