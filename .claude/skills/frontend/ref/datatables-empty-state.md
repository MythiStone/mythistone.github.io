---
name: datatables-empty-state
description: A DataTables-initialized table whose empty state is a colspan placeholder <tr> inside the same table throws "Requested unknown parameter '1' for row 0, column 1"; wrap the whole <table> in {% if rows %} and put the empty state in a plain <p>. Use when adding or editing a curated table that gets .DataTable(), or when a page logs that DataTables warning on load.
files:
  - assets/js/dungeon-page.js
  - assets/js/item.js
  - templates/dungeon_page.html
  - templates/item.html
---

# DataTables empty-state placeholder rows crash the table

Curated tables are initialised with `$(el).DataTable({ columnDefs: [...], ordering:false, paging:false, ... })` and target column indices in `columnDefs`. On `templates/dungeon_page.html` the init loop in `assets/js/dungeon-page.js` covers `lust-table`, `popular-comps-table`, `best-loot-table` and `skip-npcs-table`; `assets/js/item.js` builds the item page tables.

If the table's empty state is a single `<tr><td colspan="N">No data yet.</td></tr>` rendered **inside** that same `<table>`, DataTables sees a row with only one cell but the `columnDefs` reference columns 1..N-1, so on load it throws:

```
DataTables warning: table id=<id> - Requested unknown parameter '1' for row 0, column 1
```

WHY: the `colspan` row is one physical `<td>`; DataTables indexes cells positionally and cannot find the columns its `columnDefs`/responsive config expect.

HOW to apply:

- **Server-rendered rows:** never put the empty-state row inside a DataTable. Wrap the entire `<table>...</table>` in `{% if rows %}` and render the empty state as a plain `<p class="text-center text-sm text-secondary p-3 mb-0">No data yet.</p>` in the `{% else %}` branch, so no table element exists when empty. The init loop's `if (el)` guard then skips it. All four dungeon page tables follow this. The trap has two disguises: an inline `{% for x in seq if cond %}...{% else %}<tr colspan>`, AND a `{% for %}` followed by a separate `{% if seq|length == 0 %}<tr colspan>{% endif %}` in the same tbody (easy to miss because the loop looks like it has no empty branch).
- **JS-built rows:** follow `assets/js/item.js` `mountTable()`: `clear()` the tbody and rebuild rows BEFORE calling `.DataTable()`, and set `language: { emptyTable: "—" }` so the empty case is DataTables-native with no placeholder row.

Test with the [[local-test-render]] workflow, or render the template with empty context and assert the `id="<table>"` element is absent.
