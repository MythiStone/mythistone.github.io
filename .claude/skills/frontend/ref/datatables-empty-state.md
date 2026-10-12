---
name: datatables-empty-state
description: A DataTables-initialized table whose empty state is a colspan placeholder <tr> inside the same table throws "Requested unknown parameter '1' for row 0, column 1"; wrap the whole <table> in {% if rows %} and put the empty state in a plain <p>. Use when adding or editing a curated table that gets .DataTable(), or when a page logs that DataTables warning on load.
kind: external
files:
  - assets/js/dungeon-page.js
  - assets/js/item.js
  - templates/dungeon_page.html
  - templates/item.html
---

# A DataTable never contains its own empty-state row

A table initialised with `.DataTable()` and `columnDefs` throws on load when its only row is a
`<td colspan="N">` placeholder:

```
DataTables warning: table id=<id> - Requested unknown parameter '1' for row 0, column 1
```

DataTables indexes cells by position, and the colspan row has one cell.

- **Server-rendered rows:** wrap the whole `<table>` in `{% if rows %}` and render the empty state
  as a plain `<p>` in the `{% else %}` branch, so no table element exists when empty. The trap has
  two disguises: `{% for x in seq if cond %} ... {% else %}<tr colspan>`, and a `{% for %}` followed
  by a separate `{% if seq|length == 0 %}<tr colspan>{% endif %}` in the same tbody.
- **JS-built rows:** follow `mountTable` in `assets/js/item.js`, which fills the tbody before the
  init and leaves the empty case to DataTables.
