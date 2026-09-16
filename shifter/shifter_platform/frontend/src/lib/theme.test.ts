import { beforeEach, describe, expect, it } from "vitest";

import { applyInitialTheme, toggleTheme } from "./theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

describe("applyInitialTheme", () => {
  it("defaults to the operational dark theme when nothing is stored", () => {
    applyInitialTheme();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("applies a stored light theme", () => {
    localStorage.setItem("shifter-theme", "light");
    applyInitialTheme();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("treats any non-light stored value as dark", () => {
    localStorage.setItem("shifter-theme", "garbage");
    applyInitialTheme();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("toggleTheme", () => {
  it("switches from dark to light and persists the choice", () => {
    document.documentElement.classList.add("dark");
    expect(toggleTheme()).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("shifter-theme")).toBe("light");
  });

  it("switches from light to dark and persists the choice", () => {
    expect(toggleTheme()).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("shifter-theme")).toBe("dark");
  });
});
