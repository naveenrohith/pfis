# Report 4: Parser and Processing Pipeline Review

## Executive Summary

The parser and processing pipeline are the heart of PFIS. The current design is strong for an MVP because parser contracts, registry routing, normalization, parse failure tracking, confidence scoring, deduplication, and raw-email retention already exist. The main risk is that `pipeline.py` owns too many stages and will become hard to reason about as more banks, formats, and connectors are added.

## Current Pipeline

Evidence:

- `backend/app/services/parser/base_parser.py` defines `BaseParser`, `ParseResult`, confidence weights, and transaction type enum.
- `backend/app/services/parser/registry.py` maps known banks to bank parsers and uses `GenericParser` as fallback.
- `backend/app/services/parser/pipeline.py` classifies email, selects parser, computes parse result, infers merchant, normalizes merchant, assigns category, deduplicates through `TransactionService`, records parse failure, and marks emails processed.
- `backend/app/services/parser/normalizer.py` maps raw merchants to normalized names and category defaults with TTL caching.
- `docs/parser.md` documents parser selection, confidence scoring, and parser rules.

## Strengths

- Parser output is represented by a structured dataclass instead of loose dictionaries.
- Confidence scoring is explainable and centralized.
- Unknown senders degrade through `GenericParser` instead of failing immediately.
- Failed parses are recorded in `ParseFailure`.
- Raw emails are retained, enabling reprocessing.
- Low-confidence parsing is visible through confidence score and review flag behavior.
- Merchant correction learning feeds back into normalization through `TransactionService`.

## Weaknesses and Risks

| Issue | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Pipeline function does too much | High | Maintainability, testing | `_process_email_batch` performs classification, parsing, inference, normalization, persistence, and failure handling | Split into named pipeline stages with isolated tests |
| Parser registry mappings are static | Medium | Scalability | `_register_defaults` hardcodes bank mapping | Introduce declarative parser metadata as banks increase |
| Generic parser may over-accept | Medium | Data quality | fallback parser is used for many banks and UPI sources | Track fallback usage and require review thresholds |
| Batch commits occur per email | Medium | Performance, partial processing | `_process_email_batch` commits inside the loop | Define transaction boundaries per batch or per stage with deliberate failure semantics |
| Confidence score lacks calibration metrics | Medium | Product trust | Scoring is rule-based but no aggregate accuracy tracking is visible | Add parser accuracy dashboards and regression fixtures |

## Parser Scalability Assessment

Current parser scalability is acceptable for HDFC, SBI, ICICI, generic UPI, and initial bank coverage. It will become fragile when PFIS supports many banks, statement formats, PDFs, SMS, and bank APIs unless parser registration, sample fixtures, versioning, and acceptance criteria become stricter.

Target model:

```text
Raw source record
  -> classifier
  -> parser selection
  -> parser result
  -> validation
  -> normalization
  -> dedup
  -> persistence
  -> review queue
```

## Recommended Solution

1. Extract pipeline stages into small functions or classes: classify, parse, enrich merchant, normalize, persist, handle failure.
2. Add fixture-driven parser tests for every supported bank and major variant.
3. Track parser name, parser version, confidence, fallback usage, and failure reason in operational outputs.
4. Keep parser modules free of database writes.
5. Use explicit review policies for low-confidence or generic-parser transactions.

## AI Integration Opportunity

AI should not replace deterministic parsers. The safer target is assistive parsing:

- suggest merchant names for review
- classify unknown formats
- propose regex candidates
- cluster parse failures
- enrich categories after deterministic extraction

AI-generated results should be marked as assisted, confidence-scored, and reviewable.

## Validation Strategy

- `pytest tests/pytest/test_parser_regression.py`
- `pytest tests/pytest/test_parser_edge_cases.py`
- `pytest tests/pytest/test_jobs_pipeline.py`
- Add regression fixtures before changing parser rules.
- Verify `ParseFailure` behavior for invalid and exception paths.

## Rollback Strategy

Parser modernization should preserve current `ParseResult` fields and transaction persistence behavior. If a new stage implementation changes extraction results unexpectedly, switch the registry back to the prior parser implementation and keep failure fixtures for diagnosis.

