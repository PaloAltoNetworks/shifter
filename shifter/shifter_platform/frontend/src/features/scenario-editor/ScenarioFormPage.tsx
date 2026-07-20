import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Loader2 } from "lucide-react";

import { useCreateScenario, useScenario, useUpdateScenario } from "@/api/scenarios";
import { ApiError } from "@/api/errors";
import type { ScenarioCreate, ScenarioDetail, ScenarioInstance, ScenarioSubnet } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import {
  emptyInstance,
  emptySubnet,
  InstancesCard,
  SubnetsCard,
  type InstanceForm,
  type SubnetForm,
} from "./ScenarioFormFields";
import { scenarioListPath, scenarioPath } from "./routes";

interface FormState {
  scenario_id: string;
  name: string;
  description: string;
  ngfw: boolean;
  instances: InstanceForm[];
  subnets: SubnetForm[];
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function fromDetail(detail: ScenarioDetail): FormState {
  return {
    scenario_id: detail.id,
    name: detail.name,
    description: detail.description,
    ngfw: detail.ngfw,
    instances: detail.instances.map((instance, index) => ({
      key: `load-${index}`,
      name: instance.name,
      role: instance.role,
      os_type: instance.os_type,
      xdr_agent: Boolean(instance.xdr_agent),
      domain_controller: Boolean(instance.domain_controller),
      join_domain: Boolean(instance.join_domain),
      ami_key: instance.ami_key ?? "",
      instance_type: instance.instance_type ?? "",
      dc_domain_name: instance.dc_config?.domain_name ?? "",
      dc_netbios_name: instance.dc_config?.netbios_name ?? "",
    })),
    subnets: detail.subnets.map((subnet, index) => ({
      key: `load-s-${index}`,
      name: subnet.name,
      instances: subnet.instances.join(", "),
      connected_to: (subnet.connected_to ?? []).join(", "),
    })),
  };
}

function toInstancePayload(instance: InstanceForm): ScenarioInstance {
  const payload: ScenarioInstance = {
    name: instance.name,
    role: instance.role,
    os_type: instance.os_type,
    xdr_agent: instance.xdr_agent,
    domain_controller: instance.domain_controller,
    join_domain: instance.join_domain,
  };
  if (instance.ami_key.trim()) payload.ami_key = instance.ami_key.trim();
  if (instance.instance_type.trim()) payload.instance_type = instance.instance_type.trim();
  if (instance.domain_controller) {
    payload.dc_config = { domain_name: instance.dc_domain_name, netbios_name: instance.dc_netbios_name };
  }
  return payload;
}

function removeAt<T>(list: T[], index: number): T[] {
  return list.filter((_, i) => i !== index);
}

function toPayload(state: FormState): ScenarioCreate {
  return {
    scenario_id: state.scenario_id,
    name: state.name,
    description: state.description,
    ngfw: state.ngfw,
    instances: state.instances.map(toInstancePayload),
    subnets: state.subnets.map(
      (subnet): ScenarioSubnet => ({
        name: subnet.name,
        instances: splitList(subnet.instances),
        connected_to: splitList(subnet.connected_to),
      }),
    ),
  };
}

export function ScenarioFormPage({ mode }: Readonly<{ mode: "create" | "edit" }>) {
  const navigate = useNavigate();
  const params = useParams();
  const scenarioId = params.scenarioId ?? "";

  const existing = useScenario(scenarioId, mode === "edit");
  const create = useCreateScenario();
  const update = useUpdateScenario(scenarioId);
  const mutation = mode === "create" ? create : update;

  // Monotonic client-side key source for form rows (stable, non-index list keys).
  const keyCounter = useRef(0);
  const nextKey = () => `row-${keyCounter.current++}`;

  const [state, setState] = useState<FormState>(() => ({
    scenario_id: "",
    name: "",
    description: "",
    ngfw: false,
    instances: [emptyInstance(nextKey())],
    subnets: [],
  }));
  const [initialized, setInitialized] = useState(mode === "create");

  useEffect(() => {
    if (mode === "edit" && existing.data && !initialized) {
      setState(fromDetail(existing.data));
      setInitialized(true);
    }
  }, [mode, existing.data, initialized]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setState((prev) => ({ ...prev, [key]: value }));
  }

  function setInstance(index: number, patch: Partial<InstanceForm>) {
    setState((prev) => ({
      ...prev,
      instances: prev.instances.map((instance, i) => (i === index ? { ...instance, ...patch } : instance)),
    }));
  }

  function setSubnet(index: number, patch: Partial<SubnetForm>) {
    setState((prev) => ({
      ...prev,
      subnets: prev.subnets.map((subnet, i) => (i === index ? { ...subnet, ...patch } : subnet)),
    }));
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const payload = toPayload(state);
    if (mode === "create") {
      create.mutate(payload, { onSuccess: (created) => navigate(scenarioPath(created.scenario_id)) });
    } else {
      update.mutate(payload, { onSuccess: () => navigate(scenarioPath(scenarioId)) });
    }
  }

  if (mode === "edit" && existing.isLoading) {
    return (
      <div className="grid place-items-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading scenario" />
      </div>
    );
  }
  if (mode === "edit" && existing.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Scenario not found</AlertTitle>
        <AlertDescription>
          This scenario may have been deleted.{" "}
          <Link className="underline" to={scenarioListPath()}>
            Back to scenarios
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }
  if (mode === "edit" && existing.data && !existing.data.editable) {
    return (
      <Alert variant="destructive">
        <AlertTitle>This scenario cannot be edited here</AlertTitle>
        <AlertDescription>
          Built-in, ACES, and CTF scenarios are read-only in the editor. You can clone it to a custom scenario instead.{" "}
          <Link className="underline" to={scenarioPath(scenarioId)}>
            Back to scenario
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const nonFieldError = mutation.error instanceof ApiError ? mutation.error.message : null;
  const cancelHref = mode === "edit" ? scenarioPath(scenarioId) : scenarioListPath();

  return (
    <div className="mx-auto max-w-3xl">
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={scenarioListPath()}>
          Scenarios
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{mode === "create" ? "New scenario" : "Edit"}</span>
      </nav>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {mode === "create" ? "New scenario" : `Edit ${existing.data?.name ?? "scenario"}`}
      </h1>

      {nonFieldError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not save</AlertTitle>
          <AlertDescription>{nonFieldError}</AlertDescription>
        </Alert>
      ) : null}

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
        <Card>
          <CardContent className="flex flex-col gap-5">
            {mode === "create" ? (
              <div className="flex flex-col gap-2">
                <Label htmlFor="f-id">Scenario ID</Label>
                <Input
                  id="f-id"
                  value={state.scenario_id}
                  placeholder="my-custom-lab"
                  onChange={(event) => set("scenario_id", event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Lowercase letters, numbers, hyphens, and underscores. Cannot be changed later.
                </p>
              </div>
            ) : null}
            <div className="flex flex-col gap-2">
              <Label htmlFor="f-name">Name</Label>
              <Input id="f-name" value={state.name} onChange={(event) => set("name", event.target.value)} />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="f-desc">Description</Label>
              <Textarea
                id="f-desc"
                rows={3}
                value={state.description}
                onChange={(event) => set("description", event.target.value)}
              />
            </div>
            <label className="flex select-none items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 rounded border-input bg-transparent accent-primary"
                checked={state.ngfw}
                onChange={(event) => set("ngfw", event.target.checked)}
              />
              <span>Requires NGFW provisioning</span>
            </label>
          </CardContent>
        </Card>

        <InstancesCard
          instances={state.instances}
          onChange={setInstance}
          onAdd={() => set("instances", [...state.instances, emptyInstance(nextKey())])}
          onRemove={(index) => set("instances", removeAt(state.instances, index))}
        />

        <SubnetsCard
          subnets={state.subnets}
          onChange={setSubnet}
          onAdd={() => set("subnets", [...state.subnets, emptySubnet(nextKey())])}
          onRemove={(index) => set("subnets", removeAt(state.subnets, index))}
        />

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => navigate(cancelHref)}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            {mode === "create" ? "Create scenario" : "Save changes"}
          </Button>
        </div>
      </form>
    </div>
  );
}
