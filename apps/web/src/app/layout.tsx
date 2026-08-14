import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { QueryProvider } from "@/components/query-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "InfluencerOS",
    template: "%s · InfluencerOS",
  },
  description: "Internal control center for AI influencer production",
  // An internal tool has no business being indexed.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#12141c",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg text-fg min-h-screen antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
