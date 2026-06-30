# Report Encoding Policy

Generated local HTML reports must not write raw non-ASCII UI text directly.

Use `scripts/report_html.py`:

- `report_html.text(value)` for all visible text and dynamic values.
- `report_html.write(path, html)` instead of `Path.write_text(...)`.
- Keep report generator source files ASCII-only. Put Chinese labels in Python
  unicode escapes, then pass them through `report_html.text(...)`.
- CSV files may use `encoding="utf-8-sig"` for Excel compatibility.

Reason: PowerShell and terminal pipes on Windows can corrupt raw Chinese text
into `????`. HTML entities render correctly in browsers and survive local
report regeneration.

