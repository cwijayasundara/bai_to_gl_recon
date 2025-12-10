"""Data models for reconciliation transactions and results."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
import re


class TransactionSource(Enum):
    """Source system for the transaction."""

    BAI2 = "bai2"
    INTACCT = "intacct"


class TransactionType(Enum):
    """Transaction type (debit or credit from bank's perspective)."""

    CREDIT = "credit"  # Money in (deposits, wire-in)
    DEBIT = "debit"  # Money out (checks, wire-out, fees)


@dataclass
class NormalizedTransaction:
    """
    Normalized transaction representation for reconciliation matching.

    This model serves as a common structure that both BAI2 and Sage Intacct
    transactions are transformed into for consistent matching.
    """

    # Unique identifier (generated or from source)
    id: str

    # Source system
    source: TransactionSource

    # Transaction date
    date: date

    # Amount in dollars (always positive, type indicates direction)
    amount: Decimal

    # Transaction type (credit/debit)
    type: TransactionType

    # Reference number (check number, wire reference, deposit ID)
    reference: Optional[str] = None

    # Normalized reference (stripped of special chars, uppercase)
    normalized_reference: Optional[str] = None

    # Transaction description
    description: str = ""

    # BAI2-specific fields
    bai2_type_code: Optional[int] = None
    bai2_type_description: Optional[str] = None

    # Intacct-specific fields
    vendor: Optional[str] = None
    gl_account: Optional[str] = None
    intacct_transaction_id: Optional[str] = None

    # Original raw data for audit trail
    raw_data: dict[str, Any] = field(default_factory=dict)

    # Matching state
    is_matched: bool = False
    match_tier: Optional[str] = None
    matched_with: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize reference after initialization."""
        if self.reference and not self.normalized_reference:
            # Remove special characters, convert to uppercase
            self.normalized_reference = re.sub(r"[^a-zA-Z0-9]", "", self.reference).upper()


@dataclass
class MatchResult:
    """Result of a transaction match attempt."""

    # Matched transactions
    bank_transaction: NormalizedTransaction
    intacct_transactions: list[NormalizedTransaction]

    # Match metadata
    match_tier: str
    match_score: float  # 0.0 to 1.0
    match_reason: str

    # Variance details (if any)
    amount_variance: Optional[Decimal] = None
    date_variance_days: Optional[int] = None

    # Timestamp for audit
    matched_at: datetime = field(default_factory=datetime.now)

    @property
    def is_exact_match(self) -> bool:
        """Check if this is a perfect match."""
        return (self.amount_variance is None or self.amount_variance == Decimal("0")) and (
            self.date_variance_days is None or self.date_variance_days == 0
        )

    @property
    def total_intacct_amount(self) -> Decimal:
        """Sum of all matched Intacct transaction amounts."""
        return sum((t.amount for t in self.intacct_transactions), Decimal("0"))


@dataclass
class ReconciliationSummary:
    """Summary of the reconciliation process."""

    # File information
    bai2_filename: str
    intacct_filename: str
    reconciliation_date: datetime
    statement_period_start: date
    statement_period_end: date

    # Transaction counts
    total_bank_transactions: int
    total_intacct_transactions: int

    # Match results
    matched_count: int
    bank_only_count: int
    intacct_only_count: int
    variance_count: int

    # Amount totals
    bank_total_credits: Decimal
    bank_total_debits: Decimal
    intacct_total_credits: Decimal
    intacct_total_debits: Decimal

    # Variance totals
    total_amount_variance: Decimal

    # Match tier breakdown
    matches_by_tier: dict[str, int] = field(default_factory=dict)

    # Processing metadata
    processing_time_seconds: float = 0.0
    config_file_used: Optional[str] = None

    @property
    def match_rate_bank(self) -> float:
        """Percentage of bank transactions matched."""
        if self.total_bank_transactions == 0:
            return 0.0
        return (self.matched_count / self.total_bank_transactions) * 100

    @property
    def match_rate_intacct(self) -> float:
        """Percentage of Intacct transactions matched."""
        if self.total_intacct_transactions == 0:
            return 0.0
        matched_intacct = self.total_intacct_transactions - self.intacct_only_count
        return (matched_intacct / self.total_intacct_transactions) * 100

    @property
    def bank_net_change(self) -> Decimal:
        """Net change from bank transactions (credits - debits)."""
        return self.bank_total_credits - self.bank_total_debits

    @property
    def intacct_net_change(self) -> Decimal:
        """Net change from Intacct transactions (credits - debits)."""
        return self.intacct_total_credits - self.intacct_total_debits
