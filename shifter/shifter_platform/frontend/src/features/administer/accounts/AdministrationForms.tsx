import { useState, type ReactNode } from "react";

import { describeMutationError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AdministrationError({ error }: Readonly<{ error: unknown }>) {
  const message = describeMutationError(error, "The operation could not be completed. No successful change was confirmed.");
  return message ? <p role="alert" className="text-destructive">{message}</p> : null;
}

export function AdministrationSection({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return <Card className="space-y-4 p-5"><h2 className="text-lg font-semibold">{title}</h2>{children}</Card>;
}

export function NameForm({ label, initial = "", submit, pending, error, onSave }: Readonly<{
  label: string; initial?: string; submit: string; pending: boolean; error: unknown; onSave: (name: string) => void;
}>) {
  const [name, setName] = useState(initial);
  const id = label.toLowerCase().replaceAll(" ", "-");
  return <form className="space-y-3" onSubmit={event => { event.preventDefault(); onSave(name.trim()); }}>
    <Label htmlFor={id}>{label}</Label><Input id={id} value={name} maxLength={200} required onChange={event => setName(event.target.value)} />
    <Button disabled={pending || !name.trim()} type="submit">{submit}</Button>
    <AdministrationError error={error} />
  </form>;
}

export function AdministrationPages({ count, offset, onOffset, label }: Readonly<{
  count: number; offset: number; onOffset: (offset: number) => void; label: string;
}>) {
  return <nav aria-label={`${label} pages`} className="flex gap-3">
    <Button variant="outline" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - 50))}>Previous {label}</Button>
    <Button variant="outline" disabled={offset + 50 >= count} onClick={() => onOffset(offset + 50)}>Next {label}</Button>
  </nav>;
}
