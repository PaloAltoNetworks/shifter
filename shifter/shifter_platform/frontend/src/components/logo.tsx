import type { SVGProps } from "react";

/**
 * Shifter brand mark: two offset chevrons stepping forward — displacement /
 * "shift" as motion. Blue gradient on transparent so it sits inside the dark
 * brand tile (see AppShell). viewBox matches the source mark (32x32).
 */
export function ShifterMark(props: Readonly<SVGProps<SVGSVGElement>>) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="shifter-mark" x1="8" y1="6" x2="26" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0a84ff" />
          <stop offset="1" stopColor="#0a66e0" />
        </linearGradient>
      </defs>
      <path
        d="M10 7 L18 16 L10 25"
        stroke="url(#shifter-mark)"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.5"
      />
      <path
        d="M17 7 L25 16 L17 25"
        stroke="url(#shifter-mark)"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
