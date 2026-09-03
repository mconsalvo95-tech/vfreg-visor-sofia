# Phase 6D revised plan: editable management charts

Status: implemented and covered by automated regression checks. Excel 2019 Plus,
Google Sheets, A4 Print Preview, and production-PC checks remain manual.

## Decision

Reject the static-PNG design and stop modifying the current `openpyxl`
`ScatterChart` output.

Build an isolated prototype with **XlsxWriter native LineCharts**. The charts
remain editable in Excel and Google Sheets, and their series remain connected
to visible worksheet cells.

The central compatibility rule is:

- chart X categories are literal text such as `12:25`, `12:30`, `12:35`;
- the date is printed separately in the report header;
- Excel serial datetimes are never passed to a chart axis.

This removes the two corrupt states already observed: `00:00` on the wrong
axis and serial values such as `46xxx`. A regular 1/5/10/15/30-minute report
already has equally spaced points, so a text-category LineChart is the correct
model.

The appearance may differ slightly between Excel 2019 and Google Sheets, but
the series, time labels, values, gaps, units, and editability must remain
correct in both.

## Visual contract

Use the WhatsApp photograph as the structural reference:

- one strongly bordered management summary;
- three stacked panels: Voltage, Current, Frequency;
- a compact visible row of times and values associated with each panel;
- simple lines without point markers;
- light gridlines, black section borders, and no unnecessary legend;
- visible date and interval for every page;
- printable A4 landscape layout;
- optional `Observaciones` and `Responsable / Firma` boxes.

Do not copy the photographed logo or company identity. Reproduce its readable,
print-oriented structure.

## Non-negotiable behavior

- `Raw Data` keeps every selected reading.
- `Datos de gráficos` keeps every plotted point and remains visible.
- Charts are native and editable after download.
- Editing a plotted value updates its chart.
- Editing minimum/maximum cells updates the optional limit series after
  recalculation.
- A missing period is blank and breaks the line; it is never converted to zero.
- A real zero remains zero.
- A real spike remains visible and is never smoothed or clipped.
- Collection remains read-only Modbus function 04 and continues during export.
- The portable Windows application remains fully offline.

## P0 — revised isolated editable prototype

The deterministic native-chart report is now connected to the local XLSX
export only; it does not change dashboard collection or VFREG communication.

1. Correct all Report formulas for Excel 2019:
   - `COUNTIFS` state criteria must use a worksheet range, for example
     `,'Datos de gráficos'!$G$2:$G$49,"<>Pausa"`;
   - never quote a worksheet range as a string, such as
     `,"'Datos de gráficos'!$G$2:$G$49","<>Pausa"`;
   - use only `IF`, `OR`, `IFERROR`, `AVERAGE`, `COUNTIFS`, and `NA`;
   - reject `_xlfn` functions, external references, and quoted range tokens.
2. Keep the 48 representative five-minute points: stable values, normal
   variation, a real spike, a real zero/production pause, and a missing
   interval. Keep `Raw Data`, `Report`, and `Datos de gráficos` visible.
   This five-minute sample validates P0 rendering only; it must not become a
   production assumption. The final writer receives the user's selected
   automatic, 1-, 5-, 10-, 15-, or 30-minute aggregation.
3. Use three native editable LineCharts with literal `HH:mm` values from
   `Hora etiqueta` as the only category source, numeric Y series, real gaps,
   no markers, no smoothing, light horizontal gridlines, no vertical
   gridlines, and at most eight X labels. Do not use Excel date serials or
   static PNG graphs.
4. Match the supplied operational-form reference more closely:
   - retain three vertically stacked panels;
   - use a bordered panel heading rather than a redundant chart title;
   - replace the narrow right-side table with an eight-column horizontal
     time/value strip above each chart;
   - span each chart across the report width at roughly 900–950 × 145–160 px;
   - preserve the bordered summary, yellow editable limits, date, interval,
     page number, Observaciones, and Responsable / Firma.
5. Start with one dense A4 landscape page, one page wide, narrow margins, and
   explicit row heights/print area. If Print Preview makes a chart under about
   35 mm high or labels unreadable, use two landscape pages rather than
   shrinking it further: Voltage and Current on page 1; Frequency,
   observations, and signature on page 2. Repeat date, interval, and page
   number on every page.
   Manual chart pages contain at most 48 aggregated points. Automatic mode
   instead keeps its bounded 600 plotted points in exactly three charts across
   two A4 pages, using X-axis tick-label skipping for readability. The
   horizontal time/value strip shows evenly sampled points from that page,
   never fixed five-minute cells.
6. Keep editable limit helper series separate from measured values. Blank
   limits must render as `#N/A`; real zero, spike, and missing values must not
   be reinterpreted.

### P0 automated checks

Extend the focused prototype test to verify:

- the exact Report formulas, including unquoted state ranges in `F6:F7`;
- all workbook XML parts parse and `ZipFile.testzip()` succeeds;
- no external links, malformed package relationships, or `_xlfn` formulas;
- three visible sheets, three native LineCharts, wide non-overlapping chart
  anchors, landscape print settings, and horizontal reading-strip formulas;
- literal categories, numeric values, no markers/smoothing, gaps, zero, spike,
  and blank interval behavior;
- parameterized input for at least 1-, 5-, and 30-minute data, proving the
  chart labels, point count, and page metadata follow the selected interval.

### P0 manual acceptance gate — pending

Record the prototype SHA-256 and open the exact file in Excel 2019 Plus and
Google Sheets. P0 fails immediately if Excel displays any recovery warning or
removes any record.

In both viewers verify editable charts, readable `HH:mm` X labels, numeric Y
axes, three wide stacked panels, no crowded labels, accurate zero/spike/gap,
and visible source data. In Excel, edit `Datos de gráficos!C21`, enter
representative limits in `B6:C8`, save, close, and reopen without repair. Check
A4 landscape Print Preview for clipping, overlap, and readable labels.

Do not start production migration until P0 is approved.

## P1 — separate data preparation from workbook writing

Implemented: the proven aggregation/statistics logic remains separate from the
XLSX writer.

1. Keep in `exports.py`:
   - SQLite selection and row limits;
   - report statistics;
   - interval validation;
   - manual regular buckets;
   - automatic sampling and genuine outage breaks.
2. Add one focused writer module, preferably
   `src/vfreg_visor/xlsx_report.py`.
3. Pass the writer plain structured values. The writer must not query SQLite or
   duplicate business rules.
4. Keep CSV export unchanged.
5. Continue producing exactly three user-facing sheets.

## P2 — XlsxWriter workbook contract

### Dependencies

1. Add `XlsxWriter>=3.2,<4` to `pyproject.toml` and update `uv.lock` only
   after P0 approval.
2. Keep `openpyxl` temporarily for regression inspection/tests.
3. After migration, remove `openpyxl` from runtime dependencies only if no
   production path still imports it; it may remain a development/test tool.
4. Update preflight messages and PyInstaller collection rules accordingly.

### `Raw Data`

- Columns remain `Fecha`, `Hora`, `Volts`, `mAmp`, `Frec`.
- Date and time remain readable manager-facing values.
- Preserve filters, frozen header, number formats, and all selected rows.

### `Datos de gráficos`

Use one row per plotted interval:

1. `Fecha` (`yyyy-mm-dd`);
2. `Hora etiqueta` (`HH:mm` text, chart category source);
3. `Volts promedio`;
4. `mAmp promedio`;
5. `Frec promedio`;
6. `Lecturas válidas`;
7. `Estado del punto` (`Dato`, `Pausa`, `Sin datos`);
8. optional helper columns for minimum/maximum limit series.

The category source must always be column 2 text. Typed dates may exist for
auditing but must never drive chart axes.

### `Report`

- Retain the black-bordered title, summary, parameter table, formulas, and
  yellow editable limit cells.
- Use native formula-driven averages and out-of-range counts.
- Stack three editable charts per page.
- Show selected date range, interval, point count, and page number.
- Use A4 landscape, fit to one page wide, explicit print area, narrow margins,
  and manual page breaks.
- Include `Observaciones` and `Responsable / Firma` boxes if approved during
  P0 review.

## P3 — editable limit lines

1. Create repeated helper series for each parameter.
2. When either limit cell is blank, helper values evaluate to `#N/A` so the
   corresponding line is not plotted.
3. When both limits exist, show:
   - dashed gray minimum;
   - dashed red maximum.
4. Keep measured values and limit values as separate native series.
5. Prototype this behavior in both Excel 2019 and Google Sheets before relying
   on it in production.
6. If Google does not recalculate the helper formulas reliably, keep the
   editable limit table/counts but make chart limit lines opt-in at download
   time. Do not silently reintroduce static images.

## P4 — tests and performance

### Automated tests

Update `tests/test_export_xlsx.py` to verify:

1. exactly three sheets and three native LineCharts per report page;
2. no ScatterChart objects;
3. chart categories reference `Hora etiqueta`, never a datetime/serial column;
4. chart values reference the correct parameter column;
5. missing intervals are blank and charts use gap behavior;
6. measured series have no markers/smoothing;
7. category label interval limits visible X labels;
8. Y axes remain numeric and use correct units;
9. limit formulas remain tied to Report limit cells;
10. Raw Data and Report statistics are identical for Automatic and every
    manual interval;
11. Report borders, validation, print area, orientation, and page breaks;
12. no external links, temporary files, or unexpected chart series.

### Integration checks — automated checks complete; manual viewer checks pending

1. Export the reported approximately 25,750-reading range.
2. Verify exact Raw Data count and bounded chart point count.
3. Verify download completes without blocking status/history endpoints.
4. Compare export time and file size against the current writer.
5. Rebuild the portable PyInstaller package and test offline XLSX export.
6. Run focused tests, the full unit suite, JavaScript syntax check, and
   `git diff --check`.

## P5 — mandatory compatibility gate (manual, pending)

Use one deterministic representative workbook and one real factory-data
workbook. Record each SHA-256 and test the exact files in both viewers.

### Excel 2019 Plus

- charts open fully configured and editable;
- X is text time and Y is numeric;
- changing values updates charts;
- entering limits updates formulas and limit lines;
- save/reopen preserves charts and layout;
- Print Preview does not clip or split panels.

### Google Sheets

- charts import with the correct series and text categories;
- no `Add a series`, `00:00` Y axis, or `46xxx` X axis;
- changing a plotted cell updates the chart;
- gaps remain gaps;
- labels remain readable even if Google changes minor styling.

Pixel-identical rendering is not required. Correct data, understandable axes,
editability, and a professional layout are required.

## Rollback and commit boundaries

1. Preserve CSV, SQLite selection, collection behavior, and dashboard behavior
   outside the native XLSX writer boundary.
2. Keep report changes focused so the writer can be revised without touching
   VFREG communication.
3. Do not push or update PR #6 until the manual viewer gates pass.

## Recommended review defaults

- Native editable LineCharts: **yes**.
- X-axis source: `HH:mm` text categories: **yes**.
- Prototype density: **48 points per page**.
- A4 landscape: **yes**.
- Value/time tables near each panel: **yes**.
- `Observaciones` and `Responsable / Firma`: **include in prototype**, remove
  later if unnecessary.
- Static PNG charts: **no**.

## Execution stop condition

Automated implementation is complete. Do not mark the manual viewer and
production-PC acceptance gates complete until they have been performed.
