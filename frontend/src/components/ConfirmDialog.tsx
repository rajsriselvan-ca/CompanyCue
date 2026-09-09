import { useEffect, useRef } from 'react';

import { Button } from '@/components/ui/primitives';

/**
 * Built on the native `<dialog>` element so focus trapping, Escape handling
 * and the inert backdrop come from the platform rather than from us.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // jsdom and older browsers may not implement showModal.
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      aria-labelledby="confirm-title"
      className="m-auto rounded-xl border border-line bg-surface p-0 text-ink shadow-panel backdrop:bg-ink/25 open:block"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      ref={ref}
    >
      <div className="w-[min(26rem,90vw)] p-5">
        <h2 className="text-base font-semibold" id="confirm-title">
          {title}
        </h2>
        <p className="mt-1.5 text-sm leading-6 text-muted">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button disabled={busy} onClick={onCancel} variant="secondary">
            Keep it
          </Button>
          <Button disabled={busy} onClick={onConfirm} variant="danger">
            {busy ? 'Deleting…' : confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
