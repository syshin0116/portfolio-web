import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "@/contexts/AuthContext";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { WebMCP } from "@/components/webmcp";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Syshin0116 Dev",
    template: "%s | Syshin0116 Dev",
  },
  description: "Syshin0116 Dev — AI Research Engineer · Blog · Projects",
  keywords: [
    "Portfolio",
    "AI Research Engineer",
    "RAG",
    "LangGraph",
    "Syshin",
    "Blog",
    "Projects",
    "Technical Portfolio",
  ],
  metadataBase: new URL("https://syshin0116.vercel.app"),
  openGraph: {
    type: "website",
    siteName: "Syshin0116 Dev",
    locale: "en_US",
    url: "https://syshin0116.vercel.app",
    title: "Syshin0116 Dev",
    description:
      "AI Research Engineer portfolio & tech blog.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Syshin0116 Dev",
    description: "AI Research Engineer portfolio & tech blog.",
    creator: "@syshin0116",
  },
  authors: [
    {
      name: "Syshin",
      url: "https://github.com/syshin0116",
    },
  ],
  creator: "Syshin",
  icons: [
    {
      rel: "icon",
      url: "/logo.png",
    },
    {
      rel: "apple-touch-icon",
      url: "/logo.png",
    },
  ],
  robots: {
    index: true,
    follow: true,
  },
  manifest: "/site.webmanifest",
  verification: {
    google: "j5FT4jTGt4vceZ-Tgn0gf5q1VHp1VNTtBcbYC1VUBFE",
  },
};

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Syshin Portfolio",
  url: "https://syshin0116.vercel.app",
  sameAs: ["https://github.com/syshin0116", "https://twitter.com/syshin0116"],
};

const personJsonLd = {
  "@context": "https://schema.org",
  "@type": "Person",
  name: "Syshin",
  url: "https://syshin0116.vercel.app",
  jobTitle: "Software Developer",
  sameAs: ["https://github.com/syshin0116", "https://twitter.com/syshin0116"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <link
          rel="alternate"
          type="application/rss+xml"
          title="Syshin0116 Dev Blog"
          href="/feed.xml"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(personJsonLd) }}
        />
      </head>
      <body className={`${geistSans.className} antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <AuthProvider>
            {children}
          </AuthProvider>
        </ThemeProvider>
        <Analytics />
        <SpeedInsights />
        <WebMCP />
      </body>
    </html>
  );
}
