import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import { WorkspaceProvider } from "@/components/workspace";

export const metadata: Metadata = {
  title: { default: "ENOT Business Platform", template: "%s · ENOT" },
  description: "Каталог и проверка бизнес-ниш",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body><WorkspaceProvider>{children}</WorkspaceProvider></body>
    </html>
  );
}
