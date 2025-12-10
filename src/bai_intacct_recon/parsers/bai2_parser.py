"""
BAI2 file parser with fallback custom parser.
Converts BAI2 transactions into normalized transaction models.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional
import logging
import re

from ..models.transaction import (
    NormalizedTransaction,
    TransactionSource,
    TransactionType,
)
from ..config import ReconConfig
from ..utils.exceptions import BAI2ParseError

logger = logging.getLogger(__name__)

# BAI2 type code ranges (per BAI2 specification)
# Credits: 100-399
# Debits: 400-699
# Loan transactions: 700-799
CREDIT_TYPE_CODE_RANGE = range(100, 400)
DEBIT_TYPE_CODE_RANGE = range(400, 700)


class BAI2Parser:
    """
    Parser for BAI2 bank statement files.

    Implements a custom parser that handles common BAI2 variations,
    then normalizes transactions into our common model.
    """

    def __init__(self, config: ReconConfig):
        """
        Initialize the parser with configuration.

        Args:
            config: Application configuration object
        """
        self.config = config
        self.type_descriptions = self._build_type_descriptions()

    def _build_type_descriptions(self) -> dict[int, str]:
        """Build a mapping of type codes to descriptions from config."""
        descriptions: dict[int, str] = {}
        transaction_types = self.config.transaction_types or {}

        for code, desc in transaction_types.get("credits", {}).items():
            descriptions[int(code)] = desc
        for code, desc in transaction_types.get("debits", {}).items():
            descriptions[int(code)] = desc

        return descriptions

    def parse_file(self, file_path: Path) -> list[NormalizedTransaction]:
        """
        Parse a BAI2 file and return normalized transactions.

        Args:
            file_path: Path to the BAI2 file

        Returns:
            List of normalized transactions

        Raises:
            BAI2ParseError: If parsing fails
        """
        logger.info(f"Parsing BAI2 file: {file_path}")

        try:
            input_config = self.config.input
            bai2_config = input_config.bai2 if hasattr(input_config, "bai2") else {}
            encoding = (
                bai2_config.get("encoding", "utf-8")
                if isinstance(bai2_config, dict)
                else "utf-8"
            )

            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()

            transactions = list(self._parse_bai2_content(content))
            logger.info(f"Extracted {len(transactions)} transactions from BAI2 file")

            return transactions
        except Exception as e:
            logger.error(f"Failed to parse BAI2 file: {e}")
            raise BAI2ParseError(f"Failed to parse BAI2 file: {e}") from e

    def _parse_bai2_content(self, content: str) -> Iterator[NormalizedTransaction]:
        """
        Parse BAI2 content using custom parser.

        Args:
            content: BAI2 file content as string

        Yields:
            Normalized transaction objects
        """
        # Remove trailing slashes and join continuation lines
        lines = self._preprocess_bai2(content)

        # Parse context
        statement_date: Optional[date] = None
        account_number: str = ""
        transaction_count = 0

        for line in lines:
            if not line.strip():
                continue

            record_type = line.split(",")[0] if "," in line else ""

            if record_type == "02":
                # Group header - extract statement date
                parts = line.split(",")
                if len(parts) >= 5:
                    date_str = parts[4]  # as_of_date field
                    statement_date = self._parse_bai2_date(date_str)

            elif record_type == "03":
                # Account identifier
                parts = line.split(",")
                if len(parts) >= 1:
                    account_number = parts[1] if len(parts) > 1 else "UNKNOWN"

            elif record_type == "16":
                # Transaction detail
                transaction_count += 1
                txn = self._parse_transaction_record(
                    line,
                    statement_date or date.today(),
                    account_number,
                    transaction_count,
                )
                if txn:
                    yield txn

    def _preprocess_bai2(self, content: str) -> list[str]:
        """
        Preprocess BAI2 content - handle continuation lines and trailing slashes.

        Args:
            content: Raw BAI2 file content

        Returns:
            List of complete record lines
        """
        # Split by lines
        raw_lines = content.strip().split("\n")

        # Remove trailing slashes and handle continuation (88 records)
        processed_lines: list[str] = []
        current_line = ""

        for line in raw_lines:
            line = line.strip()
            if not line:
                continue

            # Remove trailing slash
            if line.endswith("/"):
                line = line[:-1]

            # Check if this is a continuation record
            if line.startswith("88,"):
                # Append to previous line (remove "88," prefix)
                current_line += line[3:]
            else:
                # Save previous line if exists
                if current_line:
                    processed_lines.append(current_line)
                current_line = line

        # Add final line
        if current_line:
            processed_lines.append(current_line)

        return processed_lines

    def _parse_transaction_record(
        self,
        line: str,
        statement_date: date,
        account_number: str,
        sequence: int,
    ) -> Optional[NormalizedTransaction]:
        """
        Parse a BAI2 type 16 transaction detail record.

        BAI2 Record 16 format:
        16,type_code,amount,funds_type,bank_ref,customer_ref,text/

        Args:
            line: Transaction record line
            statement_date: Date from group header
            account_number: Bank account number
            sequence: Transaction sequence number

        Returns:
            Normalized transaction or None if parsing fails
        """
        parts = line.split(",")

        if len(parts) < 3:
            logger.warning(f"Invalid transaction record: {line}")
            return None

        try:
            # Parse fields
            type_code = int(parts[1])
            amount_cents = int(parts[2])

            # Optional fields
            funds_type = parts[3] if len(parts) > 3 else ""
            bank_reference = parts[4] if len(parts) > 4 else ""
            customer_reference = parts[5] if len(parts) > 5 else ""
            text = parts[6] if len(parts) > 6 else ""

            # Determine transaction type from type code
            if type_code in CREDIT_TYPE_CODE_RANGE:
                txn_type = TransactionType.CREDIT
            elif type_code in DEBIT_TYPE_CODE_RANGE:
                txn_type = TransactionType.DEBIT
            else:
                logger.warning(
                    f"Unknown BAI2 type code: {type_code}, defaulting to DEBIT"
                )
                txn_type = TransactionType.DEBIT

            # Convert amount from cents to dollars
            amount_dollars = Decimal(str(amount_cents)) / Decimal("100")

            # Use bank_reference as the primary reference
            reference = bank_reference if bank_reference else customer_reference

            # Generate unique ID
            txn_id = f"BAI2-{account_number}-{sequence:05d}"

            return NormalizedTransaction(
                id=txn_id,
                source=TransactionSource.BAI2,
                date=statement_date,
                amount=amount_dollars,
                type=txn_type,
                reference=reference,
                description=text,
                bai2_type_code=type_code,
                bai2_type_description=self.type_descriptions.get(type_code, "Unknown"),
                raw_data={
                    "type_code": type_code,
                    "amount_cents": amount_cents,
                    "funds_type": funds_type,
                    "bank_reference": bank_reference,
                    "customer_reference": customer_reference,
                    "text": text,
                },
            )

        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse transaction record: {line}, error: {e}")
            return None

    def _parse_bai2_date(self, date_str: str) -> date:
        """
        Parse a BAI2 date string (YYMMDD format).

        Args:
            date_str: Date string in YYMMDD format

        Returns:
            Python date object
        """
        if not date_str:
            return date.today()

        input_config = self.config.input
        bai2_config = input_config.bai2 if hasattr(input_config, "bai2") else {}
        date_format = (
            bai2_config.get("date_format", "%y%m%d")
            if isinstance(bai2_config, dict)
            else "%y%m%d"
        )

        try:
            return datetime.strptime(date_str, date_format).date()
        except ValueError:
            logger.warning(f"Could not parse BAI2 date: {date_str}")
            return date.today()

    def get_file_summary(self, file_path: Path) -> dict:
        """
        Get summary information from a BAI2 file.

        Args:
            file_path: Path to the BAI2 file

        Returns:
            Dictionary with file summary information
        """
        input_config = self.config.input
        bai2_config = input_config.bai2 if hasattr(input_config, "bai2") else {}
        encoding = (
            bai2_config.get("encoding", "utf-8")
            if isinstance(bai2_config, dict)
            else "utf-8"
        )

        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()

        lines = self._preprocess_bai2(content)

        summary: dict = {
            "sender_id": "",
            "receiver_id": "",
            "file_creation_date": "",
            "groups": [],
        }

        current_group: Optional[dict] = None
        current_account: Optional[dict] = None

        for line in lines:
            parts = line.split(",")
            record_type = parts[0] if parts else ""

            if record_type == "01":
                # File header
                if len(parts) > 1:
                    summary["sender_id"] = parts[1]
                if len(parts) > 2:
                    summary["receiver_id"] = parts[2]
                if len(parts) > 3:
                    summary["file_creation_date"] = parts[3]

            elif record_type == "02":
                # Group header
                current_group = {
                    "originator_id": parts[1] if len(parts) > 1 else "",
                    "as_of_date": parts[4] if len(parts) > 4 else "",
                    "accounts": [],
                }
                summary["groups"].append(current_group)

            elif record_type == "03":
                # Account identifier
                if current_group is not None:
                    current_account = {
                        "account_number": parts[1] if len(parts) > 1 else "",
                        "currency": parts[2] if len(parts) > 2 else "USD",
                        "transaction_count": 0,
                    }
                    current_group["accounts"].append(current_account)

            elif record_type == "16":
                # Transaction detail
                if current_account is not None:
                    current_account["transaction_count"] += 1

        return summary
