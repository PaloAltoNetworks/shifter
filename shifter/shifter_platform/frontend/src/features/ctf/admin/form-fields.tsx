/**
 * Small, shared form-field primitives for the CTF organizer create/edit forms.
 * They mirror the Risk Register / Scenario Editor form style (label + control +
 * inline field error, `aria-invalid` / `aria-describedby` wired for a11y). UI
 * affordances only; the `/api/v1/ctf/` serializers stay the authoritative
 * validator, so server field errors flow in via the `error` prop.
 */
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

export function FieldError({ id, error }: Readonly<{ id: string; error?: string }>) {
  if (!error) return null;
  return (
    <p id={id} className="text-sm text-destructive">
      {error}
    </p>
  );
}

interface BaseFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
}

export function TextField({
  id,
  label,
  value,
  onChange,
  error,
  type,
  min,
  max,
  placeholder,
}: Readonly<BaseFieldProps & { type?: string; min?: number; max?: number; placeholder?: string }>) {
  const errorId = `${id}-e`;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        min={min}
        max={max}
        placeholder={placeholder}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      <FieldError id={errorId} error={error} />
    </div>
  );
}

export function TextAreaField({
  id,
  label,
  value,
  onChange,
  error,
  rows = 3,
  placeholder,
}: Readonly<BaseFieldProps & { rows?: number; placeholder?: string }>) {
  const errorId = `${id}-e`;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        rows={rows}
        placeholder={placeholder}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      <FieldError id={errorId} error={error} />
    </div>
  );
}

export function SelectField({
  id,
  label,
  value,
  onChange,
  error,
  options,
  labelFor,
}: Readonly<
  BaseFieldProps & { options: readonly string[]; labelFor?: (value: string) => string }
>) {
  const errorId = `${id}-e`;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full" aria-invalid={error ? true : undefined}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {labelFor ? labelFor(option) : option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FieldError id={errorId} error={error} />
    </div>
  );
}

export function CheckboxField({
  id,
  label,
  checked,
  onChange,
}: Readonly<{ id: string; label: string; checked: boolean; onChange: (checked: boolean) => void }>) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm select-none">
      <input
        id={id}
        type="checkbox"
        className="size-4 rounded border-input bg-transparent accent-primary"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
