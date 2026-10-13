# Frozen numerical baseline

`reference_outputs.json` was generated from commit `3d0d122` (engine
revision `engine-2026.10.12b`, 234 tests passing) **before** any
capability-expansion work began.

It exists for one purpose: to make it impossible to silently change an
existing scientific result while adding new features.

`tests/test_baseline_regression.py` replays every entry and compares it
against the live engine. If a number moves, that test fails and the change
has to be either reverted or justified in writing.

Regenerate it **only** when a change to a scientific result has been
deliberately reviewed and documented. Regenerating it to make a failing
test pass defeats its entire purpose.

Recorded at baseline:

| Quantity | Value |
| --- | --- |
| Held-out Theoph AAFE (1-cmt FOA) | 1.293153 |
| Held-out Indometh AAFE (2-cmt) | 1.334954 |
| PBPK predicted theophylline Vss | 0.479735 L/kg |
| Theophylline a-priori absorption, Cmax AAFE | 1.074868 |
| Theophylline a-priori absorption, AUC AAFE | 1.141952 |
| Theophylline a-priori absorption, tmax AAFE | 1.641753 |
| Mean predicted fabs | 0.984228 |
