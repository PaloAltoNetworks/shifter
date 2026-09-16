import { Link } from "react-router";

import { Compass } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Recoverable client-router not-found state for an unknown SPA path (#1368). */
export function NotFoundPage() {
  return (
    <div className="grid place-items-center py-24 text-center">
      <div className="max-w-sm">
        <Compass className="mx-auto mb-4 size-8 text-muted-foreground" />
        <h1 className="text-lg font-semibold tracking-tight">Page not found</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The page you are looking for does not exist or has moved.
        </p>
        <Link to="/" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-4")}>
          Back to home
        </Link>
      </div>
    </div>
  );
}
