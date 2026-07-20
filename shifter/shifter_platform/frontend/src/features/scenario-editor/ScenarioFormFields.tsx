import type { ReactNode } from "react";

import { Plus, Trash2 } from "lucide-react";

import { INSTANCE_OS_TYPES, INSTANCE_ROLES, type ScenarioInstance } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { titleCase } from "./format";

/** One instance row of the structured editor. `key` is a stable client-side id
 * (not sent to the API) so React list keys never depend on the array index. */
export interface InstanceForm {
  key: string;
  name: string;
  role: ScenarioInstance["role"];
  os_type: ScenarioInstance["os_type"];
  xdr_agent: boolean;
  domain_controller: boolean;
  join_domain: boolean;
  ami_key: string;
  instance_type: string;
  dc_domain_name: string;
  dc_netbios_name: string;
}

export interface SubnetForm {
  key: string;
  name: string;
  instances: string;
  connected_to: string;
}

export function emptyInstance(key: string): InstanceForm {
  return {
    key,
    name: "",
    role: "victim",
    os_type: "from_agent",
    xdr_agent: false,
    domain_controller: false,
    join_domain: false,
    ami_key: "",
    instance_type: "",
    dc_domain_name: "",
    dc_netbios_name: "",
  };
}

export function emptySubnet(key: string): SubnetForm {
  return { key, name: "", instances: "", connected_to: "" };
}

/** Checkbox with wrapped label text (explicit span avoids ambiguous JSX spacing). */
function CheckboxField({
  checked,
  onChange,
  children,
}: Readonly<{ checked: boolean; onChange: (value: boolean) => void; children: ReactNode }>) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-4 rounded border-input bg-transparent accent-primary"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{children}</span>
    </label>
  );
}

function TextField({
  id,
  label,
  value,
  placeholder,
  onChange,
}: Readonly<{ id: string; label: string; value: string; placeholder?: string; onChange: (value: string) => void }>) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function InstanceFieldset({
  instance,
  index,
  removable,
  onChange,
  onRemove,
}: Readonly<{
  instance: InstanceForm;
  index: number;
  removable: boolean;
  onChange: (patch: Partial<InstanceForm>) => void;
  onRemove: () => void;
}>) {
  return (
    <fieldset className="flex flex-col gap-3 rounded-md border border-border/60 p-4">
      <legend className="px-1 text-xs text-muted-foreground">Instance {index + 1}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField id={`i-name-${index}`} label="Name" value={instance.name} onChange={(v) => onChange({ name: v })} />
        <div className="flex flex-col gap-2">
          <Label htmlFor={`i-role-${index}`}>Role</Label>
          <Select value={instance.role} onValueChange={(v) => onChange({ role: v as InstanceForm["role"] })}>
            <SelectTrigger id={`i-role-${index}`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INSTANCE_ROLES.map((value) => (
                <SelectItem key={value} value={value}>
                  {titleCase(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`i-os-${index}`}>OS type</Label>
          <Select value={instance.os_type} onValueChange={(v) => onChange({ os_type: v as InstanceForm["os_type"] })}>
            <SelectTrigger id={`i-os-${index}`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INSTANCE_OS_TYPES.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <TextField
          id={`i-type-${index}`}
          label="Instance type (optional)"
          value={instance.instance_type}
          placeholder="m5.large"
          onChange={(v) => onChange({ instance_type: v })}
        />
        <TextField
          id={`i-ami-${index}`}
          label="AMI key (optional)"
          value={instance.ami_key}
          onChange={(v) => onChange({ ami_key: v })}
        />
      </div>
      <div className="flex flex-wrap gap-4">
        <CheckboxField checked={instance.xdr_agent} onChange={(v) => onChange({ xdr_agent: v })}>
          XDR agent
        </CheckboxField>
        <CheckboxField checked={instance.domain_controller} onChange={(v) => onChange({ domain_controller: v })}>
          Domain controller
        </CheckboxField>
        <CheckboxField checked={instance.join_domain} onChange={(v) => onChange({ join_domain: v })}>
          Join domain
        </CheckboxField>
      </div>
      {instance.domain_controller ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            id={`i-dc-domain-${index}`}
            label="Domain name"
            value={instance.dc_domain_name}
            placeholder="lab.local"
            onChange={(v) => onChange({ dc_domain_name: v })}
          />
          <TextField
            id={`i-dc-netbios-${index}`}
            label="NetBIOS name"
            value={instance.dc_netbios_name}
            placeholder="LAB"
            onChange={(v) => onChange({ dc_netbios_name: v })}
          />
        </div>
      ) : null}
      {removable ? (
        <div className="flex justify-end">
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            <Trash2 className="size-4" /> Remove
          </Button>
        </div>
      ) : null}
    </fieldset>
  );
}

export function InstancesCard({
  instances,
  onChange,
  onAdd,
  onRemove,
}: Readonly<{
  instances: InstanceForm[];
  onChange: (index: number, patch: Partial<InstanceForm>) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}>) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Instances</h2>
          <Button type="button" variant="outline" size="sm" onClick={onAdd}>
            <Plus className="size-4" /> Add instance
          </Button>
        </div>
        {instances.map((instance, index) => (
          <InstanceFieldset
            key={instance.key}
            instance={instance}
            index={index}
            removable={instances.length > 1}
            onChange={(patch) => onChange(index, patch)}
            onRemove={() => onRemove(index)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

export function SubnetsCard({
  subnets,
  onChange,
  onAdd,
  onRemove,
}: Readonly<{
  subnets: SubnetForm[];
  onChange: (index: number, patch: Partial<SubnetForm>) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}>) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Subnets</h2>
          <Button type="button" variant="outline" size="sm" onClick={onAdd}>
            <Plus className="size-4" /> Add subnet
          </Button>
        </div>
        {subnets.length === 0 ? <p className="text-sm text-muted-foreground">No subnets defined.</p> : null}
        {subnets.map((subnet, index) => (
          <fieldset key={subnet.key} className="flex flex-col gap-3 rounded-md border border-border/60 p-4">
            <legend className="px-1 text-xs text-muted-foreground">Subnet {index + 1}</legend>
            <TextField
              id={`s-name-${index}`}
              label="Name"
              value={subnet.name}
              onChange={(v) => onChange(index, { name: v })}
            />
            <div className="flex flex-col gap-2">
              <Label htmlFor={`s-inst-${index}`}>Instances</Label>
              <Input
                id={`s-inst-${index}`}
                value={subnet.instances}
                placeholder="Attacker, Victim"
                onChange={(event) => onChange(index, { instances: event.target.value })}
              />
              <p className="text-xs text-muted-foreground">Comma-separated instance names in this subnet.</p>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor={`s-conn-${index}`}>Connected to (optional)</Label>
              <Input
                id={`s-conn-${index}`}
                value={subnet.connected_to}
                placeholder="core"
                onChange={(event) => onChange(index, { connected_to: event.target.value })}
              />
              <p className="text-xs text-muted-foreground">Comma-separated subnet names this subnet can reach.</p>
            </div>
            <div className="flex justify-end">
              <Button type="button" variant="ghost" size="sm" onClick={() => onRemove(index)}>
                <Trash2 className="size-4" /> Remove
              </Button>
            </div>
          </fieldset>
        ))}
      </CardContent>
    </Card>
  );
}
