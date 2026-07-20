/**
 * Markdown rendering for organizer-authored challenge content (CTF-117).
 * react-markdown renders to React elements — raw HTML in the source is NOT
 * injected (no dangerouslySetInnerHTML), so organizer content stays inert.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownContent({ text }: Readonly<{ text: string }>) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none text-sm [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
