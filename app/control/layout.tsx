import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Proms | Local control",
  description: "Local proxy browser launch control",
};

export default function ControlLayout({ children }: Readonly<{ children: ReactNode }>) {
  return children;
}
