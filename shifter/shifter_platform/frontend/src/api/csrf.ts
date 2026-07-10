/**
 * CSRF cookie access. Mirrors the existing portal pattern
 * (static/js/ctf-register.js): read Django's default `csrftoken` cookie and
 * send it as the `X-CSRFToken` header on unsafe requests. The SPA host view
 * primes the cookie via `@ensure_csrf_cookie`.
 */
export function getCookie(name: string): string {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop()?.split(";").shift() ?? "";
  }
  return "";
}

export function getCsrfToken(): string {
  return getCookie("csrftoken");
}
