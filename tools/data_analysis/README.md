# Data Analysis Tools

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
report includes endpoint tables, plate heatmaps, flagged outlier summaries, and
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
