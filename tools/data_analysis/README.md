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
Flagged endpoint outliers are shown as red replicate traces in the timecourse
plots and mapped by plate location under `heatmaps_endpoint_outliers/`; they are
not excluded from means, standard deviations, CVs, or heatmaps.
