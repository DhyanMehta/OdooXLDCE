import type { ReactNode } from "react";

type ShellProps = {
  children: ReactNode;
};

export function Shell({ children }: ShellProps) {
  return (
    <div className="shell">
      <div className="shell__glow" aria-hidden="true" />
      <main className="shell__main">{children}</main>
    </div>
  );
}
