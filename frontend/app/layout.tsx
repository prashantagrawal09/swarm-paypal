import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { SiteHeader } from "@/components/site-header";
import { Toaster } from "@/components/toaster";
import { ServerGate } from "@/components/wake-screen";
import { THEME_SCRIPT } from "@/lib/theme";

import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const DESCRIPTION =
  "Small shops buy alone and pay retail. Swarm's AI agents pool their orders, negotiate with suppliers and settle everything through PayPal.";

export const metadata: Metadata = {
  // Where the site lives, so shared links carry the preview image. Render sets
  // RENDER_EXTERNAL_URL for the web service; NEXT_PUBLIC_SITE_URL overrides it.
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? process.env.RENDER_EXTERNAL_URL ?? "http://localhost:3000",
  ),
  title: { default: "Swarm · neighbourhood buying power", template: "%s · Swarm" },
  description: DESCRIPTION,
  openGraph: {
    title: "Swarm: small shops buy like a chain",
    description: DESCRIPTION,
    siteName: "Swarm",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Swarm: small shops buy like a chain",
    description: DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f5f1" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0d0d" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en-SG"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        <Providers>
          <a
            href="#main"
            className="focus:bg-surface sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:px-3 focus:py-2"
          >
            Skip to content
          </a>
          <SiteHeader />
          <main id="main" className="flex flex-1 flex-col">
            <ServerGate>{children}</ServerGate>
          </main>
          <footer className="border-line border-t">
            <div className="text-muted mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs sm:px-6">
              <span>Swarm · Tiong Bahru, Singapore</span>
              <span>Payments by PayPal (sandbox). Agents suggest; code decides every amount.</span>
            </div>
          </footer>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
