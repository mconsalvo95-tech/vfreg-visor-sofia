# Phase 6A design notes

## Audience

The primary audience is a normal factory operator who should not need to
understand Modbus, network ports, SQLite, or collector internals. Managers use
the same application to inspect history and download reports.

## Proposed information architecture

1. **Monitoreo en vivo** — immediate process state, three measurements, trends,
   current-workday summary, and recent readings.
2. **Historial** — time and quality filters with a readable table and a download
   action that uses the same selected period.
3. **Reportes** — guided selection of period and format, with an explanation of
   CSV raw data versus XLSX Raw Data + Report.

## Visual principles

- Use the company brand in the application shell, not as an alarm color.
- Reserve red for faults/out-of-range values and amber for delayed/stale data.
- Communicate every state with text and an icon in addition to color.
- Prioritize large live measurements over technical diagnostics.
- Keep controls and labels large enough for a 1366×768 factory display.
- Avoid decorative gauges; use numbers and time-series trends instead.
- Keep movement subtle and respect reduced-motion preferences.

## Prototype-only controls

The yellow **Prototipo Fase 6A** bar and its simulated-state selector exist only
for design review. They let reviewers inspect normal, production-paused,
out-of-range, stale, and disconnected states without a live device. They are
not part of the proposed production operator interface.

## Confirmed production-pause behavior

Factory observation on 2026-08-21 confirmed that Volts and mAmp can fall to
zero while frequency continues during a planned production stop. The final
application must show **Producción detenida** while keeping the independent
connection state as **Conectado**. Raw readings remain stored; the condition is
not missing data or a connection fault. Production averages exclude the
zero-valued Volts and mAmp samples, while frequency remains available.

## Confirmed export direction represented in the mockup

- CSV is a clean raw table: Fecha, Hora, Volts, mAmp, and Frec.
- XLSX contains Raw Data and Report worksheets.
- Report limits are blank and employee-editable.
- Blank limits mean Not configured, never zero.
- Power BI is not shown in the active interface.

## Inputs still required

- Approved company logo in SVG or transparent PNG format.
- Primary company brand color.
- Final confirmation of all Spanish operator wording during Phase 6E.
- Approved logo and final color refinement may be completed after the
  operational Phase 6 interface is stable.

## Phase 6A approval checklist

- [x] Company/product hierarchy is understandable.
- [x] Live state is understandable within a few seconds.
- [x] Connection and data-quality states are clearly different.
- [x] History filters are easy for an operator to use.
- [x] CSV versus XLSX is explained clearly.
- [x] The three report scopes match factory workflows.
- [x] The layout is comfortable at 1366×768.
- [x] Stakeholder approval received to move to Phase 6B; final manager/operator
  validation remains required in Phase 6E.
