export type Theme = "dark" | "light";

const STORAGE_KEY = "shifter-theme";

function store(): Storage | null {
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

/** Apply the persisted theme (dark by default — the operational default). */
export function applyInitialTheme(): void {
  const stored = store()?.getItem(STORAGE_KEY);
  const theme: Theme = stored === "light" ? "light" : "dark";
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function toggleTheme(): Theme {
  const next: Theme = document.documentElement.classList.contains("dark") ? "light" : "dark";
  document.documentElement.classList.toggle("dark", next === "dark");
  store()?.setItem(STORAGE_KEY, next);
  return next;
}
