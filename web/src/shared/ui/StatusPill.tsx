import type { ReactNode } from "react";

interface StatusPillProps {
  tone: "neutral" | "info" | "success" | "warning";
  children: ReactNode;
}

export function StatusPill({ tone, children }: StatusPillProps) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}
