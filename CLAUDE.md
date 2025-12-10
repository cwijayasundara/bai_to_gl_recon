# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BAI2 to Sage Intacct bank reconciliation CLI tool. Matches bank transactions (BAI2 format) with general ledger entries (Intacct CSV) using a multi-tier matching algorithm.

## Commands

```bash
# Install
pip install -e .              # Basic install
pip install -e ".[dev]"       # With dev dependencies

# Run CLI
bai-recon reconcile <bai2_file> <intacct_file> -o report.xlsx
bai-recon parse-bai2 sample_data/bank_statement.bai
bai-recon parse-intacct sample_data/sage_intacct_transactions.csv
bai-recon init-config -o config.yaml

# Test
pytest                        # Run all tests
pytest tests/unit/test_parser.py::test_function  # Single test
pytest --cov=src/bai_intacct_recon              # With coverage

# Code quality
black src/                    # Format (line-length: 100)
ruff check src/               # Lint
mypy src/                     # Type check (strict mode)
```

## Architecture

```
CLI (cli.py) → ReconciliationEngine (matching/engine.py)
                    ↓
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
Parsers         Strategies      Reports
(BAI2/Intacct)  (4 tiers)       (Excel)
    ↓               ↓               ↓
    └───────────────┴───────────────┘
                    ↓
            Data Models
    (NormalizedTransaction, MatchResult)
```

### Key Data Flow

1. **Parsers** convert source files → `NormalizedTransaction` (common format)
   - BAI2: amounts in cents, dates from Record 02 group header
   - Intacct: CSV with Debit/Credit columns

2. **ReconciliationEngine.reconcile()** orchestrates matching:
   - Applies exclusion rules (bank fees, GL-only entries)
   - Runs strategies in priority order (first match wins)
   - Returns `(matches, bank_only, intacct_only)`

3. **Strategies** implement `MatchingStrategy` ABC:
   - `ExactMatchStrategy`: reference + amount + date exact
   - `FuzzyDateStrategy`: date within N days tolerance
   - `AmountToleranceStrategy`: amount within $X or Y%
   - `FuzzyDescriptionStrategy`: text similarity via `difflib.SequenceMatcher`

4. **ExcelReportGenerator** creates 6-sheet report with conditional formatting

### Configuration

YAML-based via Pydantic models in `config.py`. Key structures:
- `ReconConfig` (root) → `MatchingConfig` → `MatchingTier[]` → `MatchingRule[]`
- `ExclusionsConfig`: bank_only_type_codes, gl_only_account_patterns

## Important Patterns

- **Transaction normalization**: `NormalizedTransaction.__post_init__()` auto-normalizes references (uppercase, strip special chars)
- **Type codes**: BAI2 100-399 = credits, 400-699 = debits
- **Exclusion matching**: Uses `fnmatch` for glob patterns on GL accounts and references
- **Strategy selection**: `ReconciliationEngine._create_strategy()` maps tier config → strategy class based on tier name and rule types

## File Format Notes

**BAI2**: Custom parser (not using bai2 library due to strict validation issues). Record 16 = transactions, amounts in cents, bank reference is the matching key.

**Intacct CSV**: 8 columns, `Reference` column is the matching key, dates in MM/DD/YYYY format.
