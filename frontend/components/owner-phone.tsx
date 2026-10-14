"use client";

/**
 * The owner's phone: the same conversation the owner has on Telegram, with the same buttons,
 * text and photo replies. Messages come from the inbox API and update live from the stream.
 */

import { Camera, CheckCheck, ChevronDown, Loader2, SendHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { cx, Skeleton } from "@/components/ui";
import { type AgentMessage, ApiError, post, postForm, type ShopSummary } from "@/lib/api";
import { initials, time } from "@/lib/format";
import { useLive } from "@/lib/live";

const QUICK_REPLIES = ["report", "help", "what did I save?"];

export function OwnerPhone({
  shop,
  shops,
  onShopChange,
  onUnauthorized,
  clock,
}: {
  shop: string;
  shops?: ShopSummary[];
  onShopChange?: (code: string) => void;
  onUnauthorized?: () => void;
  clock?: string;
}) {
  const key = `/api/owners/${shop}/inbox?limit=150`;
  const { data, mutate, error } = useSWR<AgentMessage[]>(key);
  const { messages: live } = useLive();
  const [text, setText] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const photo = useRef<HTMLInputElement>(null);
  const { data: allShops } = useSWR<ShopSummary[]>(shops ? null : "/api/shops");
  const owner = `owner:${shop}`;
  const current = (shops ?? allShops)?.find((s) => s.code === shop);

  const thread = useMemo(() => {
    const byId = new Map<string, AgentMessage>();
    for (const m of data ?? []) byId.set(m.id, m);
    for (const m of live) {
      if ((m.to === owner || m.from === owner) && !byId.has(m.id)) byId.set(m.id, m);
    }
    return [...byId.values()].sort((a, b) => a.seq - b.seq);
  }, [data, live, owner]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [thread.length, shop]);

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) onUnauthorized?.();
  }, [error, onUnauthorized]);

  async function run(label: string, action: () => Promise<unknown>) {
    setSending(label);
    setProblem(null);
    try {
      await action();
      await mutate();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized?.();
      setProblem(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSending(null);
    }
  }

  const press = (actionId: string) =>
    run(actionId, () => post(`/api/owners/${shop}/actions`, { action_id: actionId }));

  const send = (value: string) => {
    const message = value.trim();
    if (!message) return;
    setText("");
    void run("text", () => post(`/api/owners/${shop}/messages`, { text: message }));
  };

  const upload = (file: File) => {
    const form = new FormData();
    form.append("photo", file);
    form.append("caption", text.trim());
    setText("");
    void run("photo", () => postForm(`/api/owners/${shop}/photo`, form));
  };

  return (
    <div className="mx-auto w-full max-w-[380px]">
      <div className="border-line-strong bg-ink dark:bg-surface-3 rounded-[2.6rem] border p-2.5 shadow-[var(--shadow)]">
        <div className="bg-page flex h-[640px] flex-col overflow-hidden rounded-[2.1rem]">
          {/* Status bar */}
          <div className="text-ink flex items-center justify-between px-6 pt-3 pb-1 text-[11px] font-semibold">
            <span className="tabular">{clock ?? "08:00"}</span>
            <span className="bg-ink dark:bg-surface-3 h-5 w-24 rounded-full" aria-hidden />
            <span className="text-ink-2">5G</span>
          </div>
          {/* Chat header */}
          <div className="border-line bg-surface flex items-center gap-3 border-b px-4 py-2.5">
            <span
              className="bg-honey grid h-9 w-9 shrink-0 place-items-center rounded-full text-xs font-bold text-[#1c1400]"
              aria-hidden
            >
              {current ? initials(current.name).toUpperCase() : null}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-ink truncate text-sm font-semibold">Swarm agent</div>
              {shops && onShopChange ? (
                <label className="text-ink-2 relative flex items-center text-xs">
                  <span className="sr-only">Act as shop</span>
                  <select
                    value={shop}
                    onChange={(event) => onShopChange(event.target.value)}
                    className="text-ink-2 w-full cursor-pointer appearance-none truncate bg-transparent pr-5 text-xs outline-none"
                  >
                    {shops.map((s) => (
                      <option key={s.code} value={s.code}>
                        for {s.owner} · {s.name}
                      </option>
                    ))}
                  </select>
                  <ChevronDown
                    className="pointer-events-none absolute right-0 h-3.5 w-3.5"
                    aria-hidden
                  />
                </label>
              ) : (
                <div className="text-ink-2 truncate text-xs">
                  {current ? `for ${current.owner}` : <Skeleton className="h-3 w-28" />}
                </div>
              )}
            </div>
          </div>

          {/* Messages */}
          <div
            ref={scroller}
            className="feed min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3"
            aria-live="polite"
          >
            {thread.length === 0 ? (
              <p className="text-muted mt-16 px-6 text-center text-xs">
                {data === undefined
                  ? "Loading the conversation..."
                  : "No messages yet. The agent writes on Monday morning with this week's order."}
              </p>
            ) : null}
            {thread.map((message) => {
              const mine = message.from === owner;
              const actions = message.payload.actions ?? [];
              const answered = message.payload.answered;
              return (
                <div
                  key={message.id}
                  className={cx("flex flex-col", mine ? "items-end" : "items-start")}
                >
                  <div
                    className={cx(
                      "max-w-[85%] rounded-2xl px-3 py-2 text-[13px] leading-snug whitespace-pre-line",
                      mine
                        ? "bg-ink text-page rounded-br-md"
                        : "border-line bg-surface text-ink rounded-bl-md border",
                    )}
                  >
                    {message.text}
                    <span
                      className={cx(
                        "tabular mt-1 flex items-center justify-end gap-1 text-[10px]",
                        mine ? "text-page/60" : "text-muted",
                      )}
                    >
                      {time(message.at)}
                      {mine ? <CheckCheck className="h-3 w-3" aria-label="sent" /> : null}
                    </span>
                  </div>
                  {actions.length ? (
                    <div
                      className="mt-1 grid w-[85%] gap-1"
                      style={{
                        gridTemplateColumns: `repeat(${Math.min(actions.length, 3)}, minmax(0, 1fr))`,
                      }}
                    >
                      {actions.map((action) => {
                        const chosen = answered === action.id;
                        return (
                          <button
                            key={action.id}
                            disabled={Boolean(answered) || sending !== null}
                            onClick={() => press(action.id)}
                            className={cx(
                              "inline-flex items-center justify-center gap-1 rounded-xl border px-2 py-1.5 text-xs font-medium transition",
                              chosen
                                ? "bg-ink text-page border-transparent"
                                : action.style === "success"
                                  ? "bg-good-soft text-good-ink border-transparent hover:brightness-95"
                                  : action.style === "danger"
                                    ? "border-line bg-surface text-critical-ink hover:bg-critical-soft"
                                    : "border-line bg-surface text-ink hover:bg-surface-2",
                              answered && !chosen && "opacity-40",
                              "disabled:cursor-not-allowed",
                            )}
                          >
                            {sending === action.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                            ) : null}
                            {action.label}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {sending === "text" || sending === "photo" ? (
              <div className="text-muted flex items-center gap-1 px-2 text-[11px]">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> agent is typing
              </div>
            ) : null}
          </div>

          {problem ? (
            <div className="bg-critical-soft text-critical-ink px-4 py-1.5 text-xs">{problem}</div>
          ) : null}

          {/* Composer */}
          <div className="border-line bg-surface border-t px-3 pt-2 pb-4">
            <div className="mb-2 flex gap-1 overflow-x-auto">
              {QUICK_REPLIES.map((reply) => (
                <button
                  key={reply}
                  onClick={() => send(reply)}
                  disabled={sending !== null}
                  className="border-line text-ink-2 hover:bg-surface-2 shrink-0 rounded-full border px-2.5 py-1 text-[11px]"
                >
                  {reply}
                </button>
              ))}
            </div>
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                send(text);
              }}
            >
              <button
                type="button"
                onClick={() => photo.current?.click()}
                className="text-ink-2 hover:bg-surface-2 grid h-9 w-9 shrink-0 place-items-center rounded-full"
                aria-label="Send a photo"
                title="Send a photo (e.g. for a damage claim)"
              >
                <Camera className="h-4 w-4" />
              </button>
              <input
                ref={photo}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) upload(file);
                  event.target.value = "";
                }}
              />
              <input
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder='Reply, e.g. "4 L less milk"'
                maxLength={1000}
                className="border-line bg-page text-ink placeholder:text-muted focus:border-line-strong h-9 min-w-0 flex-1 rounded-full border px-3.5 text-[13px] outline-none"
                aria-label="Message"
              />
              <button
                type="submit"
                disabled={!text.trim() || sending !== null}
                className="bg-honey grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#1c1400] transition disabled:opacity-40"
                aria-label="Send"
              >
                <SendHorizontal className="h-4 w-4" />
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
