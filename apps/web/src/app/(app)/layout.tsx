import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";

/** Every route in this group is behind the session guard in `AppShell`. */
export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
