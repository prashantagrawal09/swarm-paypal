"use client";

/** AG Grid, themed from the same CSS tokens as the rest of the app (light and dark). */

import {
  AllCommunityModule,
  type ColDef,
  type GetRowIdParams,
  ModuleRegistry,
  themeQuartz,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";

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

export function DataGrid<T extends { id?: string }>({
  rows,
  columns,
  height = 380,
  empty = "Nothing here yet.",
  loading = false,
}: {
  rows: T[] | undefined;
  columns: ColDef<T>[];
  height?: number;
  empty?: string;
  loading?: boolean;
}) {
  if (!loading && rows && rows.length === 0) return <Empty>{empty}</Empty>;
  // Short tables size to their rows; long ones scroll inside `height`.
  const auto = rows !== undefined && rows.length <= AUTO_HEIGHT_ROWS;
  return (
    <div style={auto ? undefined : { height }} className="w-full">
      <AgGridReact<T>
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
  );
}
