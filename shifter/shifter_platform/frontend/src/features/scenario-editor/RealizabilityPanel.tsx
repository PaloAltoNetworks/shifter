/**
 * Backend realizability panel for the Scenario Editor (#1581, ADR-034-R3).
 *
 * ADR-034-R3 requires non-realizability to be surfaced to the author rather than
 * discovered at launch. The server owns the entire assessment; this component
 * only renders it — it never re-derives an outcome, parses a gap message, or
 * decides what is publishable. The publication gate is enforced server-side, so
 * this panel is explanation, not enforcement.
 *
 * `indeterminate` is rendered distinctly from `realizable`: "we could not check"
 * must never read as "this works".
 */
import { Card, CardContent } from "@/components/ui/card";
import { useScenarioRealizability } from "@/api/scenarios";
import type { ScenarioRealizabilityGap } from "@/api/types";

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium";

/**
 * Presentation for each closed outcome.
 *
 * `dot` is supplementary only — the `label` carries the meaning, so the status
 * is never colour-only (matches the SourceBadge convention in `badges.tsx`).
 */
const OUTCOME_PRESENTATION: Record<string, { label: string; dot: string; summary: string }> = {
  realizable: {
    label: "Realizable",
    dot: "#30d158",
    summary: "The selected backend can realize this scenario.",
  },
  not_realizable: {
    label: "Not realizable",
    dot: "#ff453a",
    summary: "The selected backend cannot realize this scenario. It cannot be enabled until these gaps are resolved.",
  },
  indeterminate: {
    label: "Cannot be checked",
    dot: "#ff9f0a",
    summary:
      "Realizability could not be determined, so this scenario cannot be enabled. Resolve the issue below and re-check.",
  },
  not_applicable: {
    label: "Not applicable",
    dot: "#8e8e93",
    summary: "Backend realizability applies to RAES packages only.",
  },
};

const CATEGORY_LABEL: Record<string, string> = {
  capability: "Backend capability",
  image_supply: "Image supply",
  source_integrity: "Package integrity",
  target: "Target backend",
};

function GapItem({ gap }: Readonly<{ gap: ScenarioRealizabilityGap }>) {
  return (
    <li className="border-white/10 border-t py-2 first:border-t-0">
      <p className="text-sm">{gap.message}</p>
      <p className="text-muted-foreground mt-0.5 text-xs">
        {CATEGORY_LABEL[gap.category] ?? gap.category} · <span className="font-mono">{gap.address}</span>
      </p>
    </li>
  );
}

export function RealizabilityPanel({
  scenarioId,
  enabled = true,
}: Readonly<{ scenarioId: string; enabled?: boolean }>) {
  const query = useScenarioRealizability(scenarioId, enabled);

  if (!enabled) return null;

  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="mb-3 text-sm font-semibold">Backend realizability</h2>
        <RealizabilityBody
          isPending={query.isPending}
          isError={query.isError}
          outcome={query.data?.outcome}
          targetId={query.data?.target_id}
          gaps={query.data?.gaps}
        />
      </CardContent>
    </Card>
  );
}

function RealizabilityBody({
  isPending,
  isError,
  outcome,
  targetId,
  gaps,
}: Readonly<{
  isPending: boolean;
  isError: boolean;
  outcome?: string;
  targetId?: string;
  gaps?: readonly ScenarioRealizabilityGap[];
}>) {
  if (isPending) {
    return (
      <output className="text-muted-foreground block text-sm">
        Checking backend realizability…
      </output>
    );
  }
  if (isError || !outcome) {
    return (
      <output className="text-muted-foreground block text-sm">
        Backend realizability could not be loaded.
      </output>
    );
  }

  const presentation = OUTCOME_PRESENTATION[outcome] ?? {
    label: outcome,
    dot: "#8e8e93",
    summary: "",
  };
  const items = gaps ?? [];

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <output className={`${CHIP} text-foreground/85`}>
          <span
            className="size-1.5 rounded-full"
            style={{ backgroundColor: presentation.dot }}
            aria-hidden="true"
          />
          {presentation.label}
        </output>
        {targetId ? <span className={`${CHIP} text-muted-foreground`}>Target: {targetId}</span> : null}
      </div>
      {presentation.summary ? <p className="text-muted-foreground mt-2 text-sm">{presentation.summary}</p> : null}
      {items.length > 0 ? (
        <ul className="mt-3">
          {items.map((gap) => (
            <GapItem key={`${gap.code}:${gap.address}`} gap={gap} />
          ))}
        </ul>
      ) : null}
    </>
  );
}
