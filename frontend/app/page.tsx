import Link from "next/link";

const PILLARS = [
  {
    title: "Buy together",
    body: "Each shop's agent pools its weekly order with the neighbourhood and negotiates with suppliers like a chain buyer.",
  },
  {
    title: "Pay only for what arrived",
    body: "PayPal holds the money on order and captures only what was delivered. Short delivery means a smaller charge, automatically.",
  },
  {
    title: "Help the neighbours",
    body: "Surplus stock is sold before it expires, and emergency supplies are borrowed from shops down the street.",
  },
];

export default function Home() {
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-16">
      <p className="text-sm font-medium text-amber-600">Tiong Bahru, Singapore</p>
      <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
        Small shops buy alone and pay retail. Swarm lets them buy together and pay like a chain.
      </h1>
      <p className="mt-5 max-w-2xl text-lg text-stone-600 dark:text-stone-400">
        Every deal, hold, invoice, payout and refund runs through PayPal.
      </p>
      <div className="mt-8 flex gap-3">
        <Link
          href="/live"
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 dark:bg-stone-100 dark:text-stone-900"
        >
          Open the live board
        </Link>
        <Link
          href="/demo"
          className="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-900"
        >
          Demo panel
        </Link>
      </div>
      <div className="mt-16 grid gap-4 sm:grid-cols-3">
        {PILLARS.map((pillar) => (
          <div
            key={pillar.title}
            className="rounded-xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900"
          >
            <h2 className="font-medium">{pillar.title}</h2>
            <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">{pillar.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
