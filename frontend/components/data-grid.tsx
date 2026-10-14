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
import { useRef, useState } from "react";

import { Empty } from "@/components/ui";
import { useMedia } from "@/lib/use-media";

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

/** One row as a phone shows it: what it is and its amount on top, the rest underneath. */
export type PhoneRow = {
  title: React.ReactNode;
  amount?: React.ReactNode;
  detail?: React.ReactNode;
  /** Small things along the bottom: status, PayPal mode and ID, time. */
  meta?: React.ReactNode;
};

const PHONE_PAGE = 25;

export function DataGrid<T extends { id?: string }>({
  rows,
  columns,
  height = 380,
  empty = "Nothing here yet.",
  loading = false,
  exportName,
  phone,
}: {
  rows: T[] | undefined;
  columns: ColDef<T>[];
  height?: number;
  empty?: string;
  loading?: boolean;
  /** Offer the table as a CSV file with this name (no extension). */
  exportName?: string;
  /** How a row reads on a phone, where a wide table would hide most of its columns. */
  phone?: (row: T) => PhoneRow;
}) {
  const grid = useRef<AgGridReact<T>>(null);
  const wide = useMedia("(min-width: 640px)", true);
  if (!loading && rows && rows.length === 0) return <Empty>{empty}</Empty>;
  if (phone && !wide) return <PhoneList rows={rows} render={phone} />;
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

function PhoneList<T extends { id?: string }>({
  rows,
  render,
}: {
  rows: T[] | undefined;
  render: (row: T) => PhoneRow;
}) {
  const [shown, setShown] = useState(PHONE_PAGE);
  if (rows === undefined) {
    return <div className="border-line h-40 rounded-[14px] border" aria-busy="true" />;
  }
  const more = rows.length - shown;
  return (
    <div>
      <ul className="border-line divide-line divide-y overflow-hidden rounded-[14px] border">
        {rows.slice(0, shown).map((row, index) => {
          const item = render(row);
          return (
            <li key={row.id ?? index} className="bg-surface px-3 py-2.5">
              <div className="flex items-baseline justify-between gap-3">
                <div className="text-ink min-w-0 text-sm font-medium">{item.title}</div>
                {item.amount !== undefined ? (
                  <div className="tabular text-ink shrink-0 text-sm font-semibold">
                    {item.amount}
                  </div>
                ) : null}
              </div>
              {item.detail ? <div className="text-ink-2 mt-0.5 text-xs">{item.detail}</div> : null}
              {item.meta ? (
                <div className="text-muted mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                  {item.meta}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {more > 0 ? (
        <button
          type="button"
          onClick={() => setShown((value) => value + PHONE_PAGE)}
          className="text-ink-2 hover:text-ink mt-2 w-full rounded-lg py-2 text-xs font-medium"
        >
          Show {Math.min(PHONE_PAGE, more)} more ({more} left)
        </button>
      ) : null}
    </div>
  );
}
