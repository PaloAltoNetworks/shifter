import { useState, type ReactNode } from "react";

import { useAddComment, useComments, useDeleteComment } from "@/api/risks";
import { ApiError } from "@/api/errors";
import type { Comment } from "@/api/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

import { ConfirmDialog } from "./ConfirmDialog";
import { formatTimestamp } from "./format";

function authorName(comment: Comment): string {
  const author = comment.author as { name?: string } | null | undefined;
  return author?.name ?? "Unknown";
}

export function CommentsPanel({
  riskId,
  canWrite,
  readOnly,
  includeDeleted = false,
}: Readonly<{ riskId: number; canWrite: boolean; readOnly: boolean; includeDeleted?: boolean }>) {
  const comments = useComments(riskId, includeDeleted);
  const addComment = useAddComment(riskId);
  const deleteComment = useDeleteComment(riskId);
  const [draft, setDraft] = useState("");
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const canModify = canWrite && !readOnly;
  const addError = addComment.error instanceof ApiError ? addComment.error : null;
  const contentError = addError?.fieldErrors().content?.[0] ?? (addError ? addError.message : undefined);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    addComment.mutate(draft, { onSuccess: () => setDraft("") });
  }

  let body: ReactNode;
  if (comments.isLoading) {
    body = <Skeleton className="h-16 w-full" />;
  } else if (comments.isError) {
    body = (
      <Alert variant="destructive">
        <AlertDescription>Could not load comments.</AlertDescription>
      </Alert>
    );
  } else if ((comments.data?.length ?? 0) === 0) {
    body = <p className="text-sm text-muted-foreground">No comments yet.</p>;
  } else {
    body = (
      <ul className="flex flex-col gap-3">
        {comments.data?.map((comment) => (
          <li key={comment.id} className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
            <div className="mb-1.5 text-xs text-muted-foreground">
              {authorName(comment)} · {formatTimestamp(comment.created_at)}
            </div>
            <p className="whitespace-pre-wrap text-sm">{comment.content}</p>
            {canModify ? (
              <div className="mt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground"
                  onClick={() => setDeleteId(comment.id ?? null)}
                  aria-label={`Delete comment by ${authorName(comment)} from ${formatTimestamp(comment.created_at)}`}
                >
                  Delete
                </Button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {canModify ? (
        <form onSubmit={submit} className="flex flex-col gap-2">
          <Label htmlFor="new-comment">Add a comment</Label>
          <Textarea
            id="new-comment"
            rows={3}
            value={draft}
            aria-invalid={contentError ? true : undefined}
            onChange={(event) => setDraft(event.target.value)}
          />
          {contentError ? <p className="text-sm text-destructive">{contentError}</p> : null}
          <div>
            <Button type="submit" size="sm" disabled={!draft.trim() || addComment.isPending}>
              Add comment
            </Button>
          </div>
        </form>
      ) : null}

      {body}

      <ConfirmDialog
        open={deleteId !== null}
        title="Delete comment?"
        confirmLabel="Delete"
        destructive
        pending={deleteComment.isPending}
        error={deleteComment.error}
        onOpenChange={(open) => {
          if (!open) {
            deleteComment.reset();
            setDeleteId(null);
          }
        }}
        onConfirm={() => {
          if (deleteId !== null) {
            deleteComment.mutate(deleteId, { onSuccess: () => setDeleteId(null) });
          }
        }}
      >
        This comment will be removed. This cannot be undone.
      </ConfirmDialog>
    </div>
  );
}
