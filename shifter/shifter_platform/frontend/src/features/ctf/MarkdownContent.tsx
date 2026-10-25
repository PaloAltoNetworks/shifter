/**
 * Markdown rendering for organizer-authored CTF content (CTF-117 / #1854).
 *
 * react-markdown renders to React elements — raw HTML in the source is NOT
 * injected (no rehype-raw, no dangerouslySetInnerHTML), so organizer content
 * stays inert. On top of that library default we pin an explicit URL policy at
 * this canonical renderer (not in individual pages): link/image URLs are
 * neutralized unless they use a safe scheme (http/https/mailto/tel) or are
 * relative/anchor, so `javascript:`, `data:`, `vbscript:` and `file:` payloads
 * cannot execute or exfiltrate in another participant's session. Callers that
 * render untrusted guidance (the briefing) additionally pass
 * `disallowedElements={["img"]}` to forbid images/remote embeds.
 */
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

const SAFE_SCHEME = /^(https?:|mailto:)/i;
const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

/**
 * Permit relative/anchor URLs and safe schemes only; neutralize everything else.
 *
 * The first gate is react-markdown's own `defaultUrlTransform`: it classifies
 * the substring before the first `:` as the protocol, so a scheme smuggled past
 * a naive prefix test with an interior control character — e.g. an
 * entity-encoded tab in `jav&#x09;ascript:` that the browser would later strip —
 * is rejected here rather than reaching the DOM. Only URLs that clear that gate
 * are then narrowed to the http/https/mailto/relative allowlist.
 */
function safeUrlTransform(url: string): string {
  const canonical = defaultUrlTransform(url);
  if (canonical === "") return "";
  const trimmed = canonical.trim();
  if (trimmed === "" || trimmed.startsWith("#") || trimmed.startsWith("/")) return canonical;
  if (!HAS_SCHEME.test(trimmed)) return canonical; // relative path, no scheme
  return SAFE_SCHEME.test(trimmed) ? canonical : "";
}

export function MarkdownContent({
  text,
  disallowedElements,
  profile,
  allowedLinkHosts = [],
}: Readonly<{ text: string; disallowedElements?: string[]; profile?: "ctf-communication-markdown/v1"; allowedLinkHosts?: readonly string[] }>) {
  const communication = profile === "ctf-communication-markdown/v1";
  const urlTransform = (url: string) => {
    if (!communication) return safeUrlTransform(url);
    const safe = defaultUrlTransform(url);
    if (!safe || safe.length > 2048 || /[\\\s]|%5c|%0[0-9a-f]|%1[0-9a-f]|%7f/i.test(safe)) return "";
    if (safe.startsWith("#")) return safe;
    if (safe.startsWith("/") && !safe.startsWith("//")) return safe;
    try {
      const parsed = new URL(safe);
      return parsed.protocol === "https:" && !parsed.username && !parsed.password &&
        allowedLinkHosts.some((host) => host.toLowerCase() === parsed.hostname.toLowerCase()) ? safe : "";
    } catch { return ""; }
  };
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        disallowedElements={communication ? [...(disallowedElements ?? []), "img", "video", "audio", "iframe", "object", "embed"] : disallowedElements}
        unwrapDisallowed
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
