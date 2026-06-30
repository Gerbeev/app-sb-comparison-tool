# v0.3.3 hardening

This release fixes the P0 issues found in solution review.

## Fixed

1. Kind-aware Stonebranch registry
2. No raw command evidence in graph JSON/CSV/report
3. Shared command normalizer
4. Normalized key collision detection
5. Mapping diagnostics
6. Safe profile commands for Stonebranch JSON and JIL

## New files in compare output

```text
compare/collisions.csv
compare/mapping-diagnostics.csv
```

## New commands

```bash
stonebranch-graph profile-stonebranch <path> -o out/profile-sb
stonebranch-graph profile-jil <path> -o out/profile-jil
```
