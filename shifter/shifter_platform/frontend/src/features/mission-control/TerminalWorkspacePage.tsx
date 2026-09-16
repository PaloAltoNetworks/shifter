/**
 * Mission Control multi-device terminal workspace (#1661).
 *
 * Legacy parity surface for `templates/mission_control/terminal.html` +
 * `static/js/terminal-layout.js`: one console for the whole active range, with
 * `tabs` and `split` layouts, per-pane device selection, and SSH plus RDP per
 * device. It owns range inventory, layout, and target reconciliation while each
 * pane (`TerminalSlot`) owns one slot's lifecycle.
 *
 * Resource budget is the visible slots — one socket in tabs mode, two in split.
 * Instances are never eagerly connected: `TERMINAL_MAX_SESSIONS_PER_USER`
 * (`config/_terminal_settings.py`) bounds a user's concurrent terminals, and a
 * large range must not be able to exhaust it by being viewed. Replacing a
 * target unmounts its `TerminalSlot`, which runs `Terminal`'s socket/xterm
 * teardown. Server-side tmux keeps the shell alive across a reattach, so
 * switching tabs costs a reconnect, not session state.
 *
 * RDP stays the server-brokered Guacamole new-tab handoff (matching legacy).
 * `config/_browser_security.py` keeps `frame-src 'none'`, and embedding the
 * Guacamole client would both need that CSP weakened and put the one-time
 * signed URL in the DOM.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";

import { Group, Panel, Separator } from "react-resizable-panels";

import { useCurrentRange } from "@/api/mission-control";
import { ApiError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { TerminalSlot } from "./TerminalSlot";
import { consoleTargetsOf, type ConsoleTarget } from "./consoleTargets";
import {
  normalizeLayout,
  reconcileSelection,
  swapIfDuplicate,
  type TerminalLayout,
} from "./terminalWorkspaceState";
import {
  readSplitSizes,
  readWorkspacePreferences,
  writeLayout,
  writeSelection,
  writeSplitSizes,
} from "./terminalWorkspaceStorage";

const LAYOUT_OPTIONS: ReadonlyArray<{ value: TerminalLayout; label: string }> = [
  { value: "tabs", label: "Tabs" },
  { value: "split", label: "Split" },
];

const PAGE_TITLE = "Terminal";
const PAGE_DESCRIPTION = "Console access to every device in your active range.";

function WorkspaceShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <PageHeader title={PAGE_TITLE} description={PAGE_DESCRIPTION} />
      {children}
    </>
  );
}

/** Segmented tabs/split control. `aria-pressed` carries state, never color alone. */
function LayoutToggle({
  layout,
  onChange,
}: Readonly<{ layout: TerminalLayout; onChange: (next: TerminalLayout) => void }>) {
  return (
    // `fieldset`/`legend` rather than `role="group"`: the native grouping
    // element is understood by assistive tech that does not implement the ARIA
    // role, and the legend names the group without a visible label.
    <fieldset className="inline-flex items-center gap-1 rounded-lg border p-[3px]">
      <legend className="sr-only">Terminal layout</legend>
      {LAYOUT_OPTIONS.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant={layout === option.value ? "secondary" : "ghost"}
          aria-pressed={layout === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </fieldset>
  );
}

/** Native select: one control, keyboard-operable, labelled per pane. */
function DeviceSelect({
  label,
  value,
  targets,
  onChange,
}: Readonly<{
  label: string;
  value: string | null;
  targets: readonly ConsoleTarget[];
  onChange: (uuid: string) => void;
}>) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-md border bg-transparent px-2 text-sm text-foreground"
      >
        {targets.map((target) => (
          <option key={target.uuid} value={target.uuid}>
            {target.private_ip ? `${target.name} (${target.private_ip})` : target.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function useWorkspaceLayout(): [TerminalLayout, (next: TerminalLayout) => void] {
  const [layout, setLayout] = useState<TerminalLayout>(() => normalizeLayout(readWorkspacePreferences().layout));
  const changeLayout = useCallback((next: TerminalLayout) => {
    setLayout(next);
    writeLayout(next);
  }, []);
  return [layout, changeLayout];
}

export function TerminalWorkspacePage() {
  const { instanceUuid: deepLinkUuid } = useParams<{ instanceUuid?: string }>();
  const query = useCurrentRange();
  const [layout, setLayout] = useWorkspaceLayout();
  // Preferred (untrusted) assignments: deep link first, then stored values.
  // They are reconciled against the live inventory on every render, so a stale
  // uuid can never reach a WebSocket or a Guacamole request.
  const [preferred, setPreferred] = useState(() => {
    const stored = readWorkspacePreferences();
    return {
      activeUuid: deepLinkUuid ?? stored.activeUuid,
      leftUuid: stored.leftUuid,
      rightUuid: stored.rightUuid,
    };
  });

  // The route param is live state, not just a bootstrap value: navigating
  // between `/mission-control/terminal/:instanceUuid` links in-app, or using
  // browser back/forward, reuses this mounted component, so the pane has to
  // follow the URL instead of staying on the device it started with.
  useEffect(() => {
    if (deepLinkUuid) {
      setPreferred((current) => (current.activeUuid === deepLinkUuid ? current : { ...current, activeUuid: deepLinkUuid }));
    }
  }, [deepLinkUuid]);

  const range = query.data?.range ?? null;
  const targets = useMemo(() => consoleTargetsOf(range), [range]);
  const isReady = range?.is_ready === true;
  const selection = useMemo(
    () => reconcileSelection(isReady ? targets : [], preferred),
    [isReady, targets, preferred],
  );

  useEffect(() => {
    if (isReady && targets.length > 0) writeSelection(selection);
  }, [isReady, targets.length, selection]);

  const targetFor = useCallback(
    (uuid: string | null) => targets.find((candidate) => candidate.uuid === uuid) ?? null,
    [targets],
  );

  if (query.isLoading) {
    return (
      <WorkspaceShell>
        <Skeleton className="h-[34rem] w-full" />
      </WorkspaceShell>
    );
  }

  if (query.isError) {
    return (
      <WorkspaceShell>
        <Alert variant="destructive">
          <AlertTitle>Could not load your range</AlertTitle>
          <AlertDescription>
            {query.error instanceof ApiError ? query.error.message : "Please retry."}
          </AlertDescription>
        </Alert>
      </WorkspaceShell>
    );
  }

  if (!range) {
    return (
      <WorkspaceShell>
        <Alert>
          <AlertTitle>No active range</AlertTitle>
          <AlertDescription>Launch a range to open terminal sessions on its devices.</AlertDescription>
        </Alert>
      </WorkspaceShell>
    );
  }

  if (!isReady) {
    return (
      <WorkspaceShell>
        <Alert>
          <AlertTitle>Range is not ready</AlertTitle>
          <AlertDescription>
            Terminal access becomes available once the range finishes provisioning.
          </AlertDescription>
        </Alert>
      </WorkspaceShell>
    );
  }

  if (targets.length === 0) {
    return (
      <WorkspaceShell>
        <Alert>
          <AlertTitle>No devices to connect to</AlertTitle>
          <AlertDescription>
            This range has no console-capable devices. NGFW appliances are managed on the NGFW pages.
          </AlertDescription>
        </Alert>
      </WorkspaceShell>
    );
  }

  return (
    <>
      <PageHeader
        title={PAGE_TITLE}
        description={PAGE_DESCRIPTION}
        actions={<LayoutToggle layout={layout} onChange={setLayout} />}
      />
      <Card className="h-[34rem] overflow-hidden p-3">
        {layout === "tabs" ? (
          <TabsLayout
            targets={targets}
            activeUuid={selection.activeUuid}
            onSelect={(uuid) => setPreferred((current) => ({ ...current, activeUuid: uuid }))}
          />
        ) : (
          <SplitLayout
            targets={targets}
            left={targetFor(selection.leftUuid)}
            right={targetFor(selection.rightUuid)}
            onSelectLeft={(uuid) => setPreferred((current) => swapIfDuplicate(current, "left", uuid))}
            onSelectRight={(uuid) => setPreferred((current) => swapIfDuplicate(current, "right", uuid))}
          />
        )}
      </Card>
    </>
  );
}

function TabsLayout({
  targets,
  activeUuid,
  onSelect,
}: Readonly<{
  targets: readonly ConsoleTarget[];
  activeUuid: string | null;
  onSelect: (uuid: string) => void;
}>) {
  return (
    <Tabs value={activeUuid ?? undefined} onValueChange={onSelect} className="h-full min-h-0">
      <TabsList className="max-w-full overflow-x-auto">
        {targets.map((target) => (
          <TabsTrigger key={target.uuid} value={target.uuid}>
            {target.name}
            {target.private_ip ? (
              <span className="ml-1.5 font-mono text-xs text-muted-foreground">{target.private_ip}</span>
            ) : null}
          </TabsTrigger>
        ))}
      </TabsList>
      {/*
        One panel per trigger so each tab controls a real element (a trigger
        whose `aria-controls` points at nothing is an aria-valid-attr-value
        violation). Radix mounts only the selected panel — no `forceMount` — so
        tabs mode still holds exactly one socket no matter how many devices the
        range has, and switching tabs is a real teardown + reconnect.
      */}
      {targets.map((target) => (
        <TabsContent key={target.uuid} value={target.uuid} className="min-h-0 flex-1">
          <TerminalSlot target={target} label="Terminal pane" tmuxWheelScrolling />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function SplitLayout({
  targets,
  left,
  right,
  onSelectLeft,
  onSelectRight,
}: Readonly<{
  targets: readonly ConsoleTarget[];
  left: ConsoleTarget | null;
  right: ConsoleTarget | null;
  onSelectLeft: (uuid: string) => void;
  onSelectRight: (uuid: string) => void;
}>) {
  // Read the persisted sizes once at mount: `defaultLayout` is an initial
  // value, so re-reading storage on every render would both cost a synchronous
  // storage hit per render and hand the group a fresh object identity.
  const [defaultLayout] = useState(() => readSplitSizes() ?? undefined);

  return (
    <Group
      orientation="horizontal"
      className="h-full"
      defaultLayout={defaultLayout}
      onLayoutChanged={(sizes, meta) => {
        if (meta.isUserInteraction) writeSplitSizes(sizes);
      }}
    >
      <Panel id="left" minSize="20%" className="min-w-0 pr-1.5">
        <TerminalSlot key={left?.uuid ?? "empty-left"} target={left} label="Left pane" tmuxWheelScrolling>
          <DeviceSelect label="Left pane device" value={left?.uuid ?? null} targets={targets} onChange={onSelectLeft} />
        </TerminalSlot>
      </Panel>
      <Separator className="w-1.5 cursor-col-resize rounded bg-border transition-colors hover:bg-primary/40" />
      <Panel id="right" minSize="20%" className="min-w-0 pl-1.5">
        <TerminalSlot key={right?.uuid ?? "empty-right"} target={right} label="Right pane" tmuxWheelScrolling>
          <DeviceSelect
            label="Right pane device"
            value={right?.uuid ?? null}
            targets={targets}
            onChange={onSelectRight}
          />
        </TerminalSlot>
      </Panel>
    </Group>
  );
}
