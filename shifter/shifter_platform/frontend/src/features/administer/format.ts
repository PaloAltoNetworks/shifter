import { titleCase } from "@/lib/format";

export { formatTimestamp } from "@/lib/format";
export { titleCase };

/** Human label for the account-origin classification returned by the API. */
export function accountOriginLabel(origin: string): string {
  switch (origin) {
    case "provider":
      return "Provider";
    case "ctf":
      return "CTF";
    case "local":
      return "Local";
    default:
      return titleCase(origin);
  }
}
