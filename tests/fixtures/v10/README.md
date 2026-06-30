# V10 Offline Fixture Corpus

Each fixture case lives under `cases/<case_id>/` and contains all files below:

- `inventory.json`: runtime Inventory snapshot
- `helper_dump.json`: helper tree captured after card entry
- `window_dump.xml`: UIAutomator XML from the same stabilization window
- `expected.json`: expected identify/mapping decision and evidence
- `scenario.json`: case metadata, environment, and legacy scenario

Rules:

1. Remove account names, serial numbers, room names, and other personal data.
2. Keep resource IDs, classes, hierarchy, bounds, and semantic labels needed by
   the test.
3. Record language, Android version, app version, and device family in
   `scenario.json`.
4. Positive cases must have corresponding negative or unknown cases where
   practical.
5. Display names must not be the only evidence supporting an expected mapping.
6. Never update an existing case to represent a new contract version. Add a new
   case and retain the original.

The `_template` case documents structure only and is not classifier evidence.
