# Data Analysis Tools

## Intended concentration grouping and manual exclusions

The **Grouping & Exclusions...** button in the analysis window controls both
kinetic and endpoint analysis. When the selected experiment contains
`experiment_design.json`, its declared reagent targets are proposed as the
analysis levels. A saved `plate_reader_analysis_settings.json` takes precedence.
Experiments without either file retain exact calculated-concentration grouping.

Review or edit the intended levels and the visible matching tolerance (initially
2% of each intended level). Each keyed calculated concentration must match
exactly one declared level. Missing, out-of-tolerance, or ambiguous values block
preview and execution; zero targets accept only numerical zero (absolute
tolerance `1e-9`). Unlisted reagent columns retain their exact values. The
preview shows each calculated range and its analysis level. The original key
and merged measurements are never rewritten to change concentrations.

For the supplied experiment the intended levels are MM = 1 mM,
pSTOPv2 = 1.25, 2.5, 5 nM, and Ribosome = 0, 0.25, 0.5, 0.75, 1 uM.
MM therefore remains a fixed condition and does not become a varying plot axis.
This maps concentrations to declared targets; it does not round measurement
signals or normalize RFU between gains. The declared targets and source-design
hash are frozen in each run's settings. If the levels are edited, their source
is recorded as user-entered. The analysis loader uses declared factor targets;
additional custom levels must be reviewed and entered explicitly.

Enter excluded wells as individual IDs or rectangular ranges such as `N1:P4`,
and provide a reason for each rule. Only measured wells may be excluded.
Conflicting reasons, invalid ranges, and exclusions leaving no usable keyed
wells are blocking errors. Exclusions apply to every timepoint and channel
before endpoint statistics, replicate outlier detection, summaries, and plots.
They apply to both the including-outliers and excluding-outliers variants.
Known preparation failures remain distinct from statistical outlier calls.
Conditions with zero remaining replicates are reported explicitly, and small
replicate counts are shown rather than being replaced with zeros or inferred
measurements.

Applied choices are saved when analysis runs, both alongside the experiment as
`plate_reader_analysis_settings.json` and inside the output as
`analysis_settings.json`. They are reused when reopening the experiment and
when switching worksheets. The app refuses malformed or unsupported saved
settings; it does not silently revert to defaults. Concurrent writes are
checked before atomic replacement. Validation preview does not write files.

Reports and exported ZIPs contain the settings, a `well_analysis_audit.csv`
with original calculated and analysis concentrations and exclusion reasons,
the unchanged raw readings in `raw_measurements.csv`, and a
`manual_exclusions.csv`. Excluded wells are shown on a separate QC plate map;
kinetic runs also include their raw traces in a separate QC plot. Excluded
readings are never included in analytical means, CVs, or outlier baselines.

The analysis CLI accepts the same saved settings:

```powershell
.\env\Scripts\python.exe tools\data_analysis\analyze_plate_reader.py --merged-csv 'C:\data\run_merged_tidy.csv' --analysis-settings 'C:\data\plate_reader_analysis_settings.json' --output-dir 'C:\data\reviewed-analysis'
```

Keep earlier results in a separate output directory when changing analysis
choices. To undo an analysis choice, edit it in **Grouping & Exclusions...**
and run into a fresh output directory. No printer configuration or firmware
rollback is involved.

## Import Tecan i-control XLSX measurements

The app's **Plate Reader Analysis** window accepts Tecan Infinite i-control
`.xlsx` fluorescence exports in both kinetic and endpoint layouts. Select the
workbook, then select its **Worksheet**, validate the preview, and run analysis.
The preview shows the selected worksheet and gain. Empty worksheets are ignored;
a workbook with one measurement sheet can be selected automatically. Multiple
measurement sheets require an explicit selection and are never combined.

Kinetic tables have wells down rows and elapsed seconds across columns; actual
fractional-second times and cycle temperatures are preserved. Endpoint grids
have lettered plate rows and numbered columns and are analyzed as a single
timepoint at zero elapsed seconds. This zero is a measurement reference, not a
reaction-start timestamp. Excitation/emission metadata identifies the channel.

For the supplied example, choose `gain 100 actual data` for the kinetic run or
`AUtogain endpoint` for the unsaturated endpoint. Missing, invalid, formula-based,
or over-range (`OVER`) readings block the selected run with an error identifying
the well. Choose an unsaturated, lower-gain acquisition rather than replacing
over-range values with zeros or silently dropping them. Different gains remain
separate acquisitions; their RFU values are not normalized or stitched together.

The CLI accepts the same worksheet selection:

```powershell
.\env\Scripts\python.exe tools\data_analysis\associate_plate_reader_and_key.py 'C:\data\experiment' --plate-file 'C:\data\reader.xlsx' --sheet 'gain 100 actual data'
.\env\Scripts\python.exe tools\data_analysis\associate_plate_reader_and_key.py 'C:\data\experiment' --plate-file 'C:\data\reader.xlsx' --sheet 'AUtogain endpoint'
```

Both layouts use the existing `concentration_key.csv` with `Well ID` and reagent
concentration columns. Unkeyed wells remain explicitly unkeyed. Default merged
CSV names include the worksheet name and a short identifier to avoid collisions.
In the app, default reports are separated under
`<experiment>/plate_reader_analysis/<worksheet identifier>/`; an explicitly
chosen output directory is used as supplied and existing-output warnings still
apply. Exported ZIP provenance records the selected sheet and includes the
original workbook copy. Legacy tab-delimited `.xls`/`.txt` imports are unchanged.
No additional Python packages or hardware access are required.

Focused validation, including the actual worker subprocess path:

```powershell
.\tools\run_worktree_tests.ps1 -PytestArgs @('-q','--run-analysis-pipeline','tests/test_tecan_plate_reader.py','tests/test_associate_plate_reader_and_key.py','tests/test_plate_reader_analysis_settings.py','tests/test_plate_reader_analysis_settings_window.py','tests/test_plate_reader_analysis_runner.py','tests/test_plate_reader_analysis_window.py','tests/test_plate_reader_analysis_export.py','tests/test_plate_reader_analysis.py')
```

## Plate Reader Endpoint Analysis

Generate endpoint replicate statistics and plate-position heatmaps from a merged
tidy plate-reader CSV:

```powershell
.\env\Scripts\python.exe tools\data_analysis\analyze_plate_reader.py FreeRTOS-interface\Experiments\PURE_sper_exp_1
```

You can also pass an existing merged tidy CSV directly:

```powershell
.\env\Scripts\python.exe tools\data_analysis\analyze_plate_reader.py --merged-csv path\to\data_merged_tidy.csv
```

Outputs are written to `plate_reader_analysis/` in the experiment directory by
default, or to `<merged_csv_stem>_analysis/` when using `--merged-csv`. The
analysis package includes `analysis_manifest.json` for downstream app
integration and `analysis_report.html` for local review/export. The report links
to endpoint tables, plate heatmaps, flagged outlier summaries, and
per-composition timecourse plots under `plate_reader_analysis/timecourses/`.
Combined per-fluorophore composition plots are written under
`plate_reader_analysis/timecourses_combined/` with inclusive and
outlier-excluded versions.
Faceted timecourse grids are written under
`plate_reader_analysis/timecourses_faceted/` when exactly two or three reagent
columns vary.
Endpoint main-effect and pairwise interaction plots are written under
`plate_reader_analysis/endpoint_effects/` with inclusive and final-outlier-
excluded variants. These are marginal descriptive endpoint summaries, not fitted
statistical models. Faceted endpoint dose-response plots are written under
`endpoint_effects/faceted_dose_response/` when exactly two or three reagent
columns vary. Endpoint main-effect and faceted dose-response plots use actual
numeric concentration values on the X axis when the plotted reagent values are
numeric; nonnumeric reagent values remain evenly spaced categories.
Endpoint replicate variability QC plots are written under
`plate_reader_analysis/endpoint_variability/` with inclusive and final-outlier-
excluded variants. These CV-vs-mean and SD-vs-mean scatter plots are descriptive
replicate QC views to help separate low-signal noise-floor behavior from
condition-level inconsistency.
Flagged endpoint outliers are shown as red replicate traces in the timecourse
plots and mapped by plate location under `heatmaps_endpoint_outliers/`; they are
not excluded from means, standard deviations, CVs, or heatmaps. Outlier calls use
a robust endpoint z-score candidate rule plus a minimum 15% endpoint difference
from the condition median. The outlier-excluded combined timecourse plot removes
only final endpoint outlier wells from that summary and plot.
