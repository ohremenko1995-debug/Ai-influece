import type { Metadata } from "next";

import { AuditLogScreen } from "@/features/audit/audit-log-screen";

export const metadata: Metadata = { title: "Audit log" };

export default function AuditPage() {
  return <AuditLogScreen />;
}
