"use client";

/** AG Grid, themed from the same CSS tokens as the rest of the app (light and dark). */

import {
  AllCommunityModule,
  type ColDef,
  type GetRowIdParams,
  ModuleRegistry,
  type ProcessCellForExportParams,
  themeQuartz,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { Download } from "lucide-react";
import { useRef } from "react";

import { Empty } from "@/components/ui";

ModuleRegistry.registerModules([AllCommunityModule]);

const AUTO_HEIGHT_ROWS = 10;

const theme = themeQuartz.withParams({
  backgroundColor: "var(--surface)",
  foregroundColor: "var(--ink)",
  textColor: "var(--ink)",
  headerTextColor: "var(--ink-2)",
  subtleTextColor: "var(--muted)",
  headerBackgroundColor: "var(--surface-2)",
  chromeBackgroundColor: "var(--surface-2)",
  oddRowBackgroundColor: "var(--surface)",
  rowHoverColor: "var(--surface-2)",
  selectedRowBackgroundColor: "var(--honey-soft)",
  borderColor: "var(--line)",
  accentColor: "var(--honey)",
  wrapperBorderRadius: 14,
  borderRadius: 8,
  fontFamily: "inherit",
  fontSize: 13,
  headerFontSize: 12,
  headerFontWeight: 500,
  spacing: 7,
  columnBorder: false,
  headerColumnBorder: false,
  wrapperBorder: { color: "var(--line)" },
  rowBorder: { color: "var(--line)" },
});

/**
 * A cell's value as a spreadsheet wants it: amounts in dollars rather than cents, names
 * rather than objects.
 */
export function exportValue(field: string | undefined, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" && field?.endsWith("_cents")) return (value / 100).toFixed(2);
  if (typeof value === "object") {
    const named = value as { name?: unknown; code?: unknown };
    return String(named.name ?? named.code ?? "");
  }
  return String(value);
}

export function DataGrid<T extends { id?: string }>({
  rows,
  columns,
  height = 380,
  empty = "Nothing here yet.",
  loading = false,
  exportName,
}: {
  rows: T[] | undefined;
  columns: ColDef<T>[];
  height?: number;
  empty?: string;
  loading?: boolean;
  /** Offer the table as a CSV file with this name (no extension). */
  exportName?: string;
}) {
  const grid = useRef<AgGridReact<T>>(null);
  if (!loading && rows && rows.length === 0) return <Empty>{empty}</Empty>;
  // Short tables size to their rows; long ones scroll inside `height`.
  const auto = rows !== undefined && rows.length <= AUTO_HEIGHT_ROWS;
  return (
    <div className="w-full">
      <div style={auto ? undefined : { height }}>
        <AgGridReact<T>
          ref={grid}
          theme={theme}
          domLayout={auto ? "autoHeight" : "normal"}
          rowData={rows ?? null}
          columnDefs={columns}
          loading={loading || rows === undefined}
          defaultColDef={{ sortable: true, resizable: true, filter: false, minWidth: 90, flex: 1 }}
          getRowId={(params: GetRowIdParams<T>) =>
            String(params.data.id ?? JSON.stringify(params.data))
          }
          animateRows
          suppressCellFocus
          enableCellTextSelection
          ensureDomOrder
        />
      </div>
      {exportName && rows?.length ? (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() =>
              grid.current?.api.exportDataAsCsv({
                fileName: `${exportName}.csv`,
                processCellCallback: (params: ProcessCellForExportParams<T>) =>
                  exportValue(params.column.getColDef().field, params.value),
              })
            }
            className="text-ink-2 hover:text-ink inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            Download as CSV
          </button>
        </div>
      ) : null}
    </div>
  );
}
