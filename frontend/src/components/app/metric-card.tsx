import type { KeyboardEvent, ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type MetricCardAction = {
  label: ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
};

type MetricCardProps = {
  label: string;
  value: ReactNode;
  helper?: ReactNode;
  icon?: ReactNode;
  onClick?: () => void;
  active?: boolean;
  actions?: MetricCardAction[];
};

export function MetricCard({
  label,
  value,
  helper,
  icon,
  onClick,
  active = false,
  actions = [],
}: MetricCardProps) {
  const interactive = typeof onClick === "function";

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!interactive || !onClick) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onClick();
  }

  return (
    <Card
      aria-pressed={interactive ? active : undefined}
      className={cn(
        "border-border/70 shadow-sm",
        interactive && "cursor-pointer transition-colors hover:border-primary/40 hover:bg-primary/5",
        active && "border-primary/40 bg-primary/5",
      )}
      onClick={onClick}
      onKeyDown={interactive ? handleKeyDown : undefined}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0 space-y-1">
          <CardTitle className="break-words text-sm font-medium text-muted-foreground">{label}</CardTitle>
          <div className="break-words text-3xl font-semibold tracking-tight">{value}</div>
        </div>
        {icon ? (
          <div className="shrink-0 rounded-2xl border bg-muted/70 p-2 text-muted-foreground">{icon}</div>
        ) : null}
      </CardHeader>
      {helper || actions.length > 0 ? (
        <CardContent className="space-y-3 pt-0 text-sm text-muted-foreground">
          {helper ? <div className="break-words">{helper}</div> : null}
          {actions.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {actions.map((action, index) => (
                <button
                  key={`metric-action-${index}`}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    action.active
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "bg-background text-muted-foreground hover:border-primary/30 hover:text-foreground",
                    action.disabled && "cursor-not-allowed opacity-50",
                  )}
                  disabled={action.disabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    action.onClick();
                  }}
                  type="button"
                >
                  {action.label}
                </button>
              ))}
            </div>
          ) : null}
        </CardContent>
      ) : null}
    </Card>
  );
}
