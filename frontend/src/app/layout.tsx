import "./globals.css";

import type { ReactNode } from "react";
import { Plus_Jakarta_Sans } from "next/font/google";

import { cn } from "@/lib/utils";

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata = {
  title: "NLC Document Intelligence",
  description: "Auditoria de documentos com IA, rastreabilidade e exportação para BI.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="pt-BR" className={cn("font-sans", plusJakartaSans.variable)}>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
