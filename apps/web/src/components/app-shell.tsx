"use client";

import { Button, Spinner, cn } from "@influenceros/ui";
import {
  CalendarDays,
  CheckCircle2,
  FileText,
  Images,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Settings2,
  Sparkles,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { RoleBadge } from "@/components/status-badge";
import { useSession } from "@/hooks/use-session";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  /** Screens from later MVP steps are listed but not linked. */
  comingSoon?: boolean;
}

const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/influencers", label: "Influencers", icon: Users },
  { href: "/audit", label: "Audit log", icon: ScrollText },
  { href: "/assets", label: "Asset library", icon: Images, comingSoon: true },
  { href: "/recipes", label: "Recipes", icon: Settings2, comingSoon: true },
  { href: "/content", label: "Content factory", icon: FileText, comingSoon: true },
  { href: "/approvals", label: "Approvals", icon: CheckCircle2, comingSoon: true },
  { href: "/calendar", label: "Calendar", icon: CalendarDays, comingSoon: true },
];

/**
 * Desktop-first shell: persistent sidebar, main region scrolls on its own.
 *
 * Also the route guard. Rendering nothing but a spinner until the session resolves
 * avoids the flash of an authenticated layout before a redirect to /login.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { me, isLoading, isAuthenticated, signOut } = useSession();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/login");
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading session" />
      </div>
    );
  }

  const activeMembership = me.memberships.find(
    (membership) => membership.organization_id === me.active_organization_id,
  );

  return (
    <div className="flex min-h-screen">
      <aside className="border-border bg-surface-1 flex w-60 shrink-0 flex-col border-r">
        <div className="flex items-center gap-2 px-4 py-4">
          <Sparkles className="text-accent size-5" aria-hidden />
          <span className="text-sm font-semibold tracking-tight">InfluencerOS</span>
        </div>

        <nav aria-label="Main" className="flex-1 px-2">
          <ul className="flex flex-col gap-0.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);

              if (item.comingSoon) {
                return (
                  <li key={item.href}>
                    <span
                      className="text-fg-subtle/60 flex cursor-not-allowed items-center gap-2.5 rounded-md px-3 py-2 text-sm"
                      title="Arrives in a later MVP step"
                    >
                      <Icon className="size-4" aria-hidden />
                      {item.label}
                      <span className="ml-auto text-[10px] uppercase tracking-wide">soon</span>
                    </span>
                  </li>
                );
              }

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-surface-3 text-fg font-medium"
                        : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                    )}
                  >
                    <Icon className="size-4" aria-hidden />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="border-border flex flex-col gap-2 border-t px-4 py-3">
          <div className="flex flex-col gap-1">
            <span className="text-fg truncate text-sm" title={me.user.email}>
              {me.user.display_name}
            </span>
            <span className="text-fg-subtle truncate text-xs" title={me.user.email}>
              {activeMembership?.organization_name ?? "—"}
            </span>
            <div className="flex items-center gap-1.5 pt-1">
              <RoleBadge role={me.active_role} />
              {me.actor_type === "agent" ? (
                <span className="text-warning-fg text-[10px] uppercase">automation</span>
              ) : null}
            </div>
          </div>
          <Button variant="ghost" size="sm" className="justify-start" onClick={signOut}>
            <LogOut aria-hidden />
            Sign out
          </Button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden">{children}</main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="border-border flex flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-fg-subtle text-sm">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}
