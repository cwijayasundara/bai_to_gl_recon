"""Configuration loader and validation for reconciliation settings."""

from pathlib import Path
from typing import Any, Optional
import logging

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class InputConfig(BaseModel):
    """Configuration for input file parsing."""

    bai2: dict[str, Any] = Field(
        default_factory=lambda: {
            "encoding": "utf-8",
            "date_format": "%y%m%d",
        }
    )
    intacct: dict[str, Any] = Field(
        default_factory=lambda: {
            "encoding": "utf-8",
            "delimiter": ",",
            "date_format": "%m/%d/%Y",
            "column_mappings": {
                "date": "Date",
                "description": "Description",
                "debit": "Debit",
                "credit": "Credit",
                "reference": "Reference",
                "vendor": "Vendor",
                "gl_account": "GL_Account",
                "transaction_id": "Transaction_ID",
            },
        }
    )


class MatchingRule(BaseModel):
    """A single matching rule within a tier."""

    field: str
    match_type: str = "exact"
    required: bool = True
    tolerance_days: Optional[int] = None
    tolerance_amount: Optional[float] = None
    tolerance_percent: Optional[float] = None
    similarity_threshold: Optional[float] = None


class MatchingTier(BaseModel):
    """A matching tier with priority and rules."""

    name: str
    description: str = ""
    priority: int = 99
    enabled: bool = True
    rules: list[MatchingRule] = Field(default_factory=list)


class MatchingSettings(BaseModel):
    """Global matching settings."""

    allow_one_to_many: bool = True
    allow_many_to_one: bool = True
    max_matches_per_transaction: int = 5
    case_sensitive: bool = False
    normalize_references: bool = True
    reference_normalize_pattern: str = "[^a-zA-Z0-9]"


class MatchingConfig(BaseModel):
    """Configuration for matching engine."""

    tiers: list[MatchingTier] = Field(default_factory=list)
    settings: MatchingSettings = Field(default_factory=MatchingSettings)


class ExclusionsConfig(BaseModel):
    """Configuration for transaction exclusions."""

    bank_only_type_codes: list[int] = Field(default_factory=lambda: [561, 108])
    gl_only_account_patterns: list[str] = Field(
        default_factory=lambda: [
            "1200-*",
            "1500-*",
            "4000-*",
            "5000-*",
            "6050-*",
            "7000-*",
            "9000-*",
        ]
    )
    gl_only_reference_patterns: list[str] = Field(
        default_factory=lambda: [
            "PREPAID-*",
            "PAYROLL-*",
            "REV-*",
            "DEPR-*",
            "INV-ADJ-*",
            "INT-EXP-*",
            "DEFREV-*",
            "RECLASS-*",
        ]
    )


class ExcelOutputConfig(BaseModel):
    """Configuration for Excel output."""

    filename_template: str = "reconciliation_report_{date}_{time}.xlsx"
    include_timestamp: bool = True


class SheetConfig(BaseModel):
    """Configuration for a report sheet."""

    enabled: bool = True
    name: str


class SheetsConfig(BaseModel):
    """Configuration for all report sheets."""

    summary: SheetConfig = Field(default_factory=lambda: SheetConfig(name="Summary"))
    matched: SheetConfig = Field(default_factory=lambda: SheetConfig(name="Matched Transactions"))
    bank_only: SheetConfig = Field(default_factory=lambda: SheetConfig(name="Bank Only"))
    intacct_only: SheetConfig = Field(default_factory=lambda: SheetConfig(name="Intacct Only"))
    amount_variances: SheetConfig = Field(
        default_factory=lambda: SheetConfig(name="Amount Variances")
    )
    audit_trail: SheetConfig = Field(default_factory=lambda: SheetConfig(name="Audit Trail"))


class OutputConfig(BaseModel):
    """Configuration for output."""

    excel: ExcelOutputConfig = Field(default_factory=ExcelOutputConfig)
    sheets: SheetsConfig = Field(default_factory=SheetsConfig)


class LoggingConfig(BaseModel):
    """Configuration for logging."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class ReconConfig(BaseModel):
    """Main configuration model for reconciliation."""

    input: InputConfig = Field(default_factory=InputConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    transaction_types: dict[str, dict[int, str]] = Field(default_factory=dict)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    config_file_path: Optional[str] = None


def get_default_config() -> dict[str, Any]:
    """Return the default configuration as a dictionary."""
    return {
        "input": {
            "bai2": {
                "encoding": "utf-8",
                "date_format": "%y%m%d",
            },
            "intacct": {
                "encoding": "utf-8",
                "delimiter": ",",
                "date_format": "%m/%d/%Y",
                "column_mappings": {
                    "date": "Date",
                    "description": "Description",
                    "debit": "Debit",
                    "credit": "Credit",
                    "reference": "Reference",
                    "vendor": "Vendor",
                    "gl_account": "GL_Account",
                    "transaction_id": "Transaction_ID",
                },
            },
        },
        "matching": {
            "tiers": [
                {
                    "name": "exact_reference_amount_date",
                    "description": "Exact match on reference, amount, and date",
                    "priority": 1,
                    "enabled": True,
                    "rules": [
                        {"field": "reference", "match_type": "exact", "required": True},
                        {"field": "amount", "match_type": "exact", "required": True},
                        {"field": "date", "match_type": "exact", "required": True},
                    ],
                },
                {
                    "name": "exact_reference_amount_fuzzy_date",
                    "description": "Exact reference and amount with date tolerance",
                    "priority": 2,
                    "enabled": True,
                    "rules": [
                        {"field": "reference", "match_type": "exact", "required": True},
                        {"field": "amount", "match_type": "exact", "required": True},
                        {
                            "field": "date",
                            "match_type": "tolerance",
                            "tolerance_days": 3,
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "exact_reference_fuzzy_amount",
                    "description": "Exact reference with amount tolerance",
                    "priority": 3,
                    "enabled": True,
                    "rules": [
                        {"field": "reference", "match_type": "exact", "required": True},
                        {
                            "field": "amount",
                            "match_type": "tolerance",
                            "tolerance_amount": 10.00,
                            "tolerance_percent": 1.0,
                            "required": True,
                        },
                        {
                            "field": "date",
                            "match_type": "tolerance",
                            "tolerance_days": 5,
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "fuzzy_description_amount",
                    "description": "Fuzzy description match with exact amount",
                    "priority": 4,
                    "enabled": True,
                    "rules": [
                        {
                            "field": "description",
                            "match_type": "fuzzy",
                            "similarity_threshold": 0.85,
                            "required": True,
                        },
                        {"field": "amount", "match_type": "exact", "required": True},
                        {
                            "field": "date",
                            "match_type": "tolerance",
                            "tolerance_days": 7,
                            "required": True,
                        },
                    ],
                },
            ],
            "settings": {
                "allow_one_to_many": True,
                "allow_many_to_one": True,
                "max_matches_per_transaction": 5,
                "case_sensitive": False,
                "normalize_references": True,
                "reference_normalize_pattern": "[^a-zA-Z0-9]",
            },
        },
        "transaction_types": {
            "credits": {
                108: "Interest Earned",
                115: "Lockbox Deposit",
                165: "ACH Credit",
                175: "Cash Deposit",
                195: "Wire Transfer In",
            },
            "debits": {
                455: "ACH Debit",
                475: "Check Paid",
                495: "Wire Transfer Out",
                561: "Bank Service Fee",
            },
        },
        "exclusions": {
            "bank_only_type_codes": [561, 108],
            "gl_only_account_patterns": [
                "1200-*",
                "1500-*",
                "4000-*",
                "5000-*",
                "6050-*",
                "7000-*",
                "9000-*",
            ],
            "gl_only_reference_patterns": [
                "PREPAID-*",
                "PAYROLL-*",
                "REV-*",
                "DEPR-*",
                "INV-ADJ-*",
                "INT-EXP-*",
                "DEFREV-*",
                "RECLASS-*",
            ],
        },
        "output": {
            "excel": {
                "filename_template": "reconciliation_report_{date}_{time}.xlsx",
                "include_timestamp": True,
            },
            "sheets": {
                "summary": {"enabled": True, "name": "Summary"},
                "matched": {"enabled": True, "name": "Matched Transactions"},
                "bank_only": {"enabled": True, "name": "Bank Only"},
                "intacct_only": {"enabled": True, "name": "Intacct Only"},
                "amount_variances": {"enabled": True, "name": "Amount Variances"},
                "audit_trail": {"enabled": True, "name": "Audit Trail"},
            },
        },
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    }


def load_config(config_path: Optional[Path] = None) -> ReconConfig:
    """
    Load configuration from a YAML file or use defaults.

    Args:
        config_path: Path to YAML configuration file (optional)

    Returns:
        ReconConfig object with loaded or default settings
    """
    config_dict = get_default_config()

    if config_path and config_path.exists():
        logger.info(f"Loading configuration from: {config_path}")
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f) or {}

        # Deep merge user config into defaults
        config_dict = _deep_merge(config_dict, user_config)
        config_dict["config_file_path"] = str(config_path)
    else:
        logger.info("Using default configuration")

    return ReconConfig(**config_dict)


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Deep merge two dictionaries.

    Args:
        base: Base dictionary
        override: Dictionary to merge on top

    Returns:
        Merged dictionary
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def generate_default_config(output_path: Path) -> None:
    """
    Generate a default configuration file.

    Args:
        output_path: Path to write the configuration file
    """
    config_dict = get_default_config()

    # Add helpful comments by using a custom YAML representer
    yaml_content = """# BAI2 to Sage Intacct Reconciliation Configuration
# Generated configuration file - customize as needed

"""
    yaml_content += yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(yaml_content)

    logger.info(f"Generated configuration file: {output_path}")
