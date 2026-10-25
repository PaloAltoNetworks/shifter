/** Safe credential metadata uses query caching; one-time secrets never do. */
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { components } from "./schema";

export type PersonalCredential = components["schemas"]["PersonalCredential"];
export type PersonalCommand = components["schemas"]["IssuePersonalCredential"];
export type IssuedCredential = components["schemas"]["IssuedPersonalCredential"];
export type ServiceCredential = components["schemas"]["ServiceCredential"];
export type ServiceCommand = components["schemas"]["CreateServiceCredential"];

export function usePersonalCredentials(offset: number) {
  return useQuery({ queryKey: ["access-credentials", "personal", offset],
    queryFn: ({ signal }) => apiFetch<components["schemas"]["PersonalCredentialPage"]>("/credentials/personal/", { signal, query: { offset } }),
  });
}

export function useServiceCredentials(offset: number) {
  return useQuery({ queryKey: ["access-credentials", "services", offset],
    queryFn: ({ signal }) => apiFetch<components["schemas"]["ServiceCredentialPage"]>("/credentials/services/", { signal, query: { offset } }),
    retry: false,
  });
}
