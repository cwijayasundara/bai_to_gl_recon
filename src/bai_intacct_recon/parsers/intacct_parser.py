"""
Sage Intacct CSV transaction parser.
Parses exported CSV files and converts to normalized transaction models.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
import logging

import pandas as pd

from ..models.transaction import (
    NormalizedTransaction,
    TransactionSource,
    TransactionType,
)
from ..config import ReconConfig
from ..utils.exceptions import IntacctParseError

logger = logging.getLogger(__name__)


class IntacctParser:
    """
    Parser for Sage Intacct CSV export files.

    Handles various CSV formats and normalizes transactions
    into the common model for reconciliation.
    """

    def __init__(self, config: ReconConfig):
        """
        Initialize the parser with configuration.

        Args:
            config: Application configuration object
        """
        self.config = config
        input_config = config.input
        intacct_config = input_config.intacct if hasattr(input_config, "intacct") else {}
        self.column_mappings = (
            intacct_config.get("column_mappings", {})
            if isinstance(intacct_config, dict)
            else {}
        )

    def parse_file(self, file_path: Path) -> list[NormalizedTransaction]:
        """
        Parse a Sage Intacct CSV file and return normalized transactions.

        Args:
            file_path: Path to the CSV file

        Returns:
            List of normalized transactions

        Raises:
            IntacctParseError: If parsing fails
        """
        logger.info(f"Parsing Intacct CSV file: {file_path}")

        try:
            input_config = self.config.input
            intacct_config = input_config.intacct if hasattr(input_config, "intacct") else {}

            if isinstance(intacct_config, dict):
                encoding = intacct_config.get("encoding", "utf-8")
                delimiter = intacct_config.get("delimiter", ",")
            else:
                encoding = "utf-8"
                delimiter = ","

            df = pd.read_csv(
                file_path,
                encoding=encoding,
                delimiter=delimiter,
            )
        except Exception as e:
            logger.error(f"Failed to read CSV file: {e}")
            raise IntacctParseError(f"Failed to read CSV file: {e}") from e

        transactions = self._process_dataframe(df)
        logger.info(f"Extracted {len(transactions)} transactions from Intacct CSV")

        return transactions

    def _process_dataframe(self, df: pd.DataFrame) -> list[NormalizedTransaction]:
        """
        Process the DataFrame and convert rows to normalized transactions.

        Args:
            df: Pandas DataFrame containing CSV data

        Returns:
            List of normalized transactions
        """
        transactions: list[NormalizedTransaction] = []

        for idx, row in df.iterrows():
            try:
                txn = self._normalize_row(row, int(idx))
                if txn:
                    transactions.append(txn)
            except Exception as e:
                logger.warning(f"Failed to process row {idx}: {e}")
                continue

        return transactions

    def _normalize_row(
        self, row: pd.Series, idx: int
    ) -> Optional[NormalizedTransaction]:
        """
        Convert a DataFrame row to a NormalizedTransaction.

        Args:
            row: Pandas Series representing a row
            idx: Row index

        Returns:
            Normalized transaction or None if row is invalid
        """
        # Get column names from config
        date_col = self.column_mappings.get("date", "Date")
        desc_col = self.column_mappings.get("description", "Description")
        debit_col = self.column_mappings.get("debit", "Debit")
        credit_col = self.column_mappings.get("credit", "Credit")
        ref_col = self.column_mappings.get("reference", "Reference")
        vendor_col = self.column_mappings.get("vendor", "Vendor")
        gl_col = self.column_mappings.get("gl_account", "GL_Account")
        txn_id_col = self.column_mappings.get("transaction_id", "Transaction_ID")

        # Parse date
        txn_date = self._parse_date(row.get(date_col))
        if not txn_date:
            logger.warning(f"Row {idx}: Invalid date, skipping")
            return None

        # Parse amount and determine type
        debit_val = self._parse_amount(row.get(debit_col))
        credit_val = self._parse_amount(row.get(credit_col))

        if debit_val and debit_val > 0:
            amount = debit_val
            txn_type = TransactionType.DEBIT
        elif credit_val and credit_val > 0:
            amount = credit_val
            txn_type = TransactionType.CREDIT
        else:
            logger.warning(f"Row {idx}: No valid amount found, skipping")
            return None

        # Extract other fields
        description = str(row.get(desc_col, "")) if pd.notna(row.get(desc_col)) else ""
        reference = str(row.get(ref_col, "")) if pd.notna(row.get(ref_col)) else None
        vendor = str(row.get(vendor_col, "")) if pd.notna(row.get(vendor_col)) else None
        gl_account = str(row.get(gl_col, "")) if pd.notna(row.get(gl_col)) else None
        intacct_txn_id = (
            str(row.get(txn_id_col, "")) if pd.notna(row.get(txn_id_col)) else None
        )

        # Generate unique ID
        txn_id = intacct_txn_id or f"INTACCT-{idx:05d}"

        return NormalizedTransaction(
            id=txn_id,
            source=TransactionSource.INTACCT,
            date=txn_date,
            amount=amount,
            type=txn_type,
            reference=reference,
            description=description,
            vendor=vendor,
            gl_account=gl_account,
            intacct_transaction_id=intacct_txn_id,
            raw_data=row.to_dict(),
        )

    def _parse_date(self, date_value) -> Optional[date]:
        """
        Parse a date value from the CSV.

        Args:
            date_value: Date value (string or datetime)

        Returns:
            Python date object or None
        """
        if pd.isna(date_value):
            return None

        if isinstance(date_value, (date, datetime)):
            return date_value if isinstance(date_value, date) else date_value.date()

        input_config = self.config.input
        intacct_config = input_config.intacct if hasattr(input_config, "intacct") else {}
        date_format = (
            intacct_config.get("date_format", "%m/%d/%Y")
            if isinstance(intacct_config, dict)
            else "%m/%d/%Y"
        )

        try:
            return datetime.strptime(str(date_value), date_format).date()
        except ValueError:
            # Try pandas parser as fallback
            try:
                return pd.to_datetime(date_value).date()
            except Exception:
                return None

    def _parse_amount(self, amount_value) -> Optional[Decimal]:
        """
        Parse an amount value from the CSV.

        Args:
            amount_value: Amount value (string, float, or None)

        Returns:
            Decimal amount or None
        """
        if pd.isna(amount_value) or amount_value == "":
            return None

        try:
            # Remove any currency symbols and commas
            if isinstance(amount_value, str):
                amount_value = amount_value.replace("$", "").replace(",", "").strip()

            return Decimal(str(amount_value))
        except (InvalidOperation, ValueError):
            return None

    def get_file_summary(self, file_path: Path) -> dict:
        """
        Get summary information from a Sage Intacct CSV file.

        Args:
            file_path: Path to the CSV file

        Returns:
            Dictionary with file summary information
        """
        input_config = self.config.input
        intacct_config = input_config.intacct if hasattr(input_config, "intacct") else {}

        if isinstance(intacct_config, dict):
            encoding = intacct_config.get("encoding", "utf-8")
            delimiter = intacct_config.get("delimiter", ",")
        else:
            encoding = "utf-8"
            delimiter = ","

        df = pd.read_csv(file_path, encoding=encoding, delimiter=delimiter)

        # Get column names
        date_col = self.column_mappings.get("date", "Date")
        debit_col = self.column_mappings.get("debit", "Debit")
        credit_col = self.column_mappings.get("credit", "Credit")
        gl_col = self.column_mappings.get("gl_account", "GL_Account")

        # Parse dates for date range
        dates = df[date_col].apply(self._parse_date).dropna()

        # Calculate totals
        debits = df[debit_col].apply(self._parse_amount).dropna()
        credits = df[credit_col].apply(self._parse_amount).dropna()

        summary = {
            "row_count": len(df),
            "columns": list(df.columns),
            "date_range": {
                "start": min(dates).isoformat() if len(dates) > 0 else None,
                "end": max(dates).isoformat() if len(dates) > 0 else None,
            },
            "totals": {
                "debit_count": len(debits),
                "credit_count": len(credits),
                "total_debits": float(sum(debits)) if len(debits) > 0 else 0,
                "total_credits": float(sum(credits)) if len(credits) > 0 else 0,
            },
            "gl_accounts": (
                df[gl_col].dropna().unique().tolist() if gl_col in df.columns else []
            ),
        }

        return summary
