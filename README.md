# BAI2 to Sage Intacct Bank Reconciliation Tool

A Python CLI application that automates the reconciliation of BAI2 bank statements with Sage Intacct general ledger transactions using a multi-tier matching algorithm.

## Features

- **Multi-Tier Matching Algorithm** - Configurable matching strategies from exact to fuzzy
- **Flexible Configuration** - YAML-based rules for matching tiers and exclusions
- **Excel Report Generation** - 6-sheet report with color-coded results
- **CLI Interface** - Rich terminal output with progress indicators
- **Extensible Architecture** - Easy to add new matching strategies

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                           │
│                      (cli.py - Click)                       │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Reconciliation Engine                    │
│                    (matching/engine.py)                     │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Parsers   │      │  Strategies │      │   Reports   │
│ BAI2/Intacct│      │ Exact/Fuzzy │      │    Excel    │
└─────────────┘      └─────────────┘      └─────────────┘
         │                    │                    │
┌─────────────────────────────────────────────────────────────┐
│                      Data Models                            │
│     NormalizedTransaction, MatchResult, Summary             │
└─────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | File | Description |
|-----------|------|-------------|
| **CLI** | `cli.py` | Click-based command interface with rich progress display |
| **Engine** | `matching/engine.py` | Orchestrates multi-tier matching with exclusion filtering |
| **Strategies** | `matching/strategies.py` | Pluggable matching algorithms (Exact, FuzzyDate, AmountTolerance, FuzzyDescription) |
| **BAI2 Parser** | `parsers/bai2_parser.py` | Custom BAI2 parser with flexible field handling |
| **Intacct Parser** | `parsers/intacct_parser.py` | Pandas-based CSV parser with configurable column mapping |
| **Report Generator** | `reports/excel_generator.py` | Multi-sheet Excel output with conditional formatting |
| **Data Models** | `models/transaction.py` | `NormalizedTransaction`, `MatchResult`, `ReconciliationSummary` dataclasses |
| **Config** | `config.py` | Pydantic-validated YAML configuration loader |

## Project Structure

```
bai_intacct_recon/
├── pyproject.toml                    # Project metadata and dependencies
├── README.md                         # This file
├── config/
│   └── default_config.yaml           # Default configuration
├── sample_data/
│   ├── README.md                     # Sample data documentation
│   ├── bank_statement.bai            # Sample BAI2 file (57 transactions)
│   └── sage_intacct_transactions.csv # Sample Intacct CSV (63 transactions)
└── src/bai_intacct_recon/
    ├── __init__.py
    ├── __main__.py                   # Entry point for python -m
    ├── cli.py                        # Click CLI commands
    ├── config.py                     # Configuration loader
    ├── parsers/
    │   ├── __init__.py
    │   ├── bai2_parser.py            # BAI2 file parser
    │   └── intacct_parser.py         # Intacct CSV parser
    ├── models/
    │   ├── __init__.py
    │   └── transaction.py            # Data models
    ├── matching/
    │   ├── __init__.py
    │   ├── engine.py                 # Reconciliation engine
    │   └── strategies.py             # Matching strategies
    ├── reports/
    │   ├── __init__.py
    │   └── excel_generator.py        # Excel report generator
    └── utils/
        ├── __init__.py
        ├── exceptions.py             # Custom exceptions
        └── logging_config.py         # Logging setup
```

## Installation

### Requirements

- Python 3.10+

### Install from source

```bash
# Clone or navigate to the project directory
cd bai_intacct_recon

# Install in development mode
pip install -e .

# Or with dev dependencies (pytest, black, ruff, mypy)
pip install -e ".[dev]"
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `pandas` | CSV parsing and data manipulation |
| `openpyxl` | Excel report generation |
| `pyyaml` | Configuration file parsing |
| `click` | CLI framework |
| `rich` | Terminal formatting and progress indicators |
| `pydantic` | Configuration validation |
| `python-dateutil` | Date parsing |

## CLI Usage

### Main Reconciliation Command

```bash
bai-recon reconcile <bai2_file> <intacct_file> [OPTIONS]
```

**Options:**
| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Custom configuration file (YAML) |
| `-o, --output PATH` | Output Excel file path |
| `--date-tolerance INT` | Override date tolerance in days |
| `--amount-tolerance FLOAT` | Override amount tolerance in dollars |
| `-v, --verbose` | Enable debug output |
| `--dry-run` | Parse files and show summary only |

**Example:**
```bash
# Basic reconciliation
bai-recon reconcile bank.bai intacct.csv -o report.xlsx

# With custom config and overrides
bai-recon reconcile bank.bai intacct.csv -c custom.yaml --date-tolerance 5 -v

# Dry run (no report generated)
bai-recon reconcile bank.bai intacct.csv --dry-run
```

### Utility Commands

```bash
# Preview BAI2 transactions
bai-recon parse-bai2 sample_data/bank_statement.bai

# Preview Intacct CSV transactions
bai-recon parse-intacct sample_data/sage_intacct_transactions.csv

# Generate sample configuration file
bai-recon init-config -o config.yaml
```

## Matching Algorithm

### Reconciliation Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT FILES                               │
│              BAI2 Bank Statement + Intacct CSV                   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PARSE & NORMALIZE                           │
│  • Convert BAI2 cents to dollars                                 │
│  • Normalize references (uppercase, strip special chars)         │
│  • Determine transaction type (credit/debit)                     │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPLY EXCLUSION RULES                         │
│  Bank-only: type codes 561 (fees), 108 (interest)               │
│  Intacct-only: GL patterns (1200-*, 4000-*, etc.)               │
│  Reference patterns: PREPAID-*, PAYROLL-*, etc.                  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MULTI-TIER MATCHING                           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TIER 1: Exact Match                                       │   │
│  │ Reference ✓ + Amount ✓ + Date ✓ → Score: 100%            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │ No match?                              │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TIER 2: Fuzzy Date                                        │   │
│  │ Reference ✓ + Amount ✓ + Date ±3 days → Score: 80-95%    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │ No match?                              │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TIER 3: Amount Tolerance                                  │   │
│  │ Reference ✓ + Amount ±$10/1% + Date ±5 days → 70-85%     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                         │ No match?                              │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TIER 4: Fuzzy Description                                 │   │
│  │ Description 85% similar + Amount ✓ + Date ±7 days        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     GENERATE RESULTS                             │
│  • Matched pairs with tier & confidence score                   │
│  • Bank-only (unmatched bank transactions)                      │
│  • Intacct-only (unmatched GL entries)                          │
│  • Amount variances (matched with differences)                   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXCEL REPORT OUTPUT                           │
│  6 sheets: Summary, Matched, Bank Only, Intacct Only,           │
│            Variances, Audit Trail                                │
└─────────────────────────────────────────────────────────────────┘
```

### Matching Tiers

Transactions are matched using a multi-tier approach, executed in priority order (first match wins):

| Tier | Strategy | Criteria | Confidence |
|------|----------|----------|------------|
| 1 | **Exact Match** | Reference + Amount + Date (all exact) | 100% |
| 2 | **Fuzzy Date** | Reference + Amount exact, Date within 3 days | 80-95% |
| 3 | **Amount Tolerance** | Reference exact, Amount within $10 or 1%, Date within 5 days | 70-85% |
| 4 | **Fuzzy Description** | Description 85% similar, Amount exact, Date within 7 days | 50-70% |

### Exclusion Rules

Transactions are pre-filtered before matching:

**Bank-Only (not expected in GL):**
- Type codes: 561 (bank fees), 108 (interest)

**Intacct-Only (GL entries not in bank):**
- Account patterns: `1200-*`, `1500-*`, `4000-*`, `5000-*`, `6050-*`, `7000-*`, `9000-*`
- Reference patterns: `PREPAID-*`, `PAYROLL-*`, `REV-*`, `DEPR-*`, `INV-ADJ-*`, etc.

## Configuration

Configuration is defined in YAML format. Use `bai-recon init-config` to generate a template.

```yaml
# Matching configuration
matching:
  tiers:
    - name: exact_reference_amount_date
      priority: 1
      enabled: true
      rules:
        - field: reference
          match_type: exact
          required: true
        - field: amount
          match_type: exact
          required: true
        - field: date
          match_type: exact
          required: true

    - name: exact_reference_amount_fuzzy_date
      priority: 2
      enabled: true
      rules:
        - field: reference
          match_type: exact
          required: true
        - field: amount
          match_type: exact
          required: true
        - field: date
          match_type: tolerance
          tolerance_days: 3
          required: true

  settings:
    allow_one_to_many: true
    normalize_references: true

# Exclusion rules
exclusions:
  bank_only_type_codes: [561, 108]
  gl_only_account_patterns:
    - "1200-*"
    - "1500-*"
    - "4000-*"
  gl_only_reference_patterns:
    - "PREPAID-*"
    - "PAYROLL-*"
```

## Excel Report

The generated Excel report contains 6 sheets:

| Sheet | Description | Highlighting |
|-------|-------------|--------------|
| **Summary** | File info, transaction counts, match rates, totals by tier | - |
| **Matched Transactions** | Bank + Intacct details, tier, score, variances | Green |
| **Bank Only** | Unmatched bank transactions | Red |
| **Intacct Only** | Unmatched GL entries | Red |
| **Amount Variances** | Matches with amount differences | Yellow |
| **Audit Trail** | Match log with timestamps and reasons | - |

## Sample Data

The `sample_data/` directory contains test files:

- `bank_statement.bai` - 57 BAI2 transactions (November 2024)
- `sage_intacct_transactions.csv` - 63 Intacct transactions

See [`sample_data/README.md`](sample_data/README.md) for detailed documentation of test scenarios.

**Expected Results:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                     ┃ Value ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total Bank Transactions    │    57 │
│ Total Intacct Transactions │    63 │
│ Matched                    │    51 │
│ Bank Only                  │     6 │
│ Intacct Only               │    12 │
│ Bank Match Rate            │ 89.5% │
│ Intacct Match Rate         │ 81.0% │
└────────────────────────────┴───────┘
```

## Input File Formats

### BAI2 File Format

The BAI2 (Bank Administration Institute Version 2) file format uses comma-delimited records terminated with `/`.

#### Record 01 - File Header
```
01,FIRSTNATL,ACME_CORP,241130,0600,1,080,10,2/
   │         │         │      │    │ │   │  └─ BAI version number
   │         │         │      │    │ │   └─ Block size
   │         │         │      │    │ └─ Physical record length
   │         │         │      │    └─ File ID (unique identifier)
   │         │         │      └─ Creation time (HHMM)
   │         │         └─ Creation date (YYMMDD)
   │         └─ Receiver ID (customer)
   └─ Sender ID (bank)
```

#### Record 02 - Group Header
```
02,ACME_CORP,021000021,1,241101,2400,,2/
   │         │         │ │      │    │ └─ As-of-date modifier
   │         │         │ │      │    └─ Currency (blank=USD)
   │         │         │ │      └─ As-of time (HHMM)
   │         │         │ └─ As-of date (YYMMDD) - transaction date
   │         │         └─ Group status (1=update)
   │         └─ Routing/ABA number
   └─ Originator ID
```

#### Record 03 - Account Identifier
```
03,123456789,USD,010,5000000,,,040,5000000,6/
   │         │   │   │       │   │   │       └─ Number of transactions
   │         │   │   │       │   │   └─ Closing balance (cents)
   │         │   │   │       │   └─ Type code (040=closing ledger)
   │         │   │   │       └─ Funds type fields (optional)
   │         │   │   └─ Opening balance (cents)
   │         │   └─ Type code (010=opening ledger)
   │         └─ Currency code
   └─ Account number
```

#### Record 16 - Transaction Detail
```
16,115,125000,0,DEP20241101001,,Customer Payment - Invoice INV-2024-001/
   │   │      │ │              │ └─ Text description
   │   │      │ │              └─ Customer reference (check number)
   │   │      │ └─ Bank reference (matching key)
   │   │      └─ Funds type (0=immediate, Z=unknown)
   │   └─ Amount in cents (125000 = $1,250.00)
   └─ Type code (see table below)
```

**BAI2 Transaction Type Codes:**

| Code | Type | Description |
|------|------|-------------|
| 108 | Credit | Interest Earned |
| 115 | Credit | Lockbox Deposit |
| 165 | Credit | ACH Credit |
| 175 | Credit | Cash/Check Deposit |
| 195 | Credit | Incoming Wire Transfer |
| 455 | Debit | ACH Debit |
| 475 | Debit | Check Paid |
| 495 | Debit | Outgoing Wire Transfer |
| 561 | Debit | Bank Service Fee |

#### Record 49/98/99 - Trailers
```
49,5000000,6/       # Account trailer: control total, record count
98,5000000,1,9/     # Group trailer: control total, num accounts, num records
99,5000000,28,144/  # File trailer: control total, num groups, num records
```

### Sage Intacct CSV Format

Standard CSV format with 8 columns:

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `Date` | Date | Yes | Transaction date (MM/DD/YYYY) | `11/01/2024` |
| `Description` | String | Yes | Transaction narrative | `Customer Payment - Invoice INV-2024-001` |
| `Debit` | Decimal | Yes* | Money out amount | `750.00` |
| `Credit` | Decimal | Yes* | Money in amount | `1250.00` |
| `Reference` | String | No | **Matching key** (check #, wire ref, deposit ID) | `DEP20241101001` |
| `Vendor` | String | No | Payee or payer name | `Customer ABC` |
| `GL_Account` | String | No | General ledger account code | `1000-Cash` |
| `Transaction_ID` | String | No | Internal Intacct identifier | `TXN-INT-001` |

*Either Debit or Credit must have a value (not both).

**Sample Row:**
```csv
11/01/2024,Customer Payment - Invoice INV-2024-001,,1250.00,DEP20241101001,Customer ABC,1000-Cash,TXN-INT-001
```

**Key Matching Fields:**
- `Reference` → matches BAI2 `Bank Reference` (field 4 in Record 16)
- `Debit`/`Credit` → matches BAI2 `Amount` (converted from cents to dollars)
- `Date` → matches BAI2 group date from Record 02

## Development

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src/bai_intacct_recon --cov-report=html
```

### Code Quality

```bash
# Format code
black src/

# Lint
ruff check src/

# Type checking
mypy src/
```

## License

MIT License
