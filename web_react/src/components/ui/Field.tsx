import { cloneElement, isValidElement, useId, type ReactNode } from 'react'

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  const id = useId()
  const control = isValidElement<{ id?: string; 'aria-describedby'?: string }>(children)
    ? cloneElement(children, { id, 'aria-describedby': hint ? `${id}-hint` : undefined }) : children
  return <div className="flex min-w-0 flex-col gap-1.5 text-sm text-stone-700">
    <label htmlFor={id} className="font-medium">{label}</label>
    {control}
    {hint && <span id={`${id}-hint`} className="text-xs leading-relaxed text-stone-500">{hint}</span>}
  </div>
}

export function Detail({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0 space-y-1">
    <dt className="text-xs text-stone-500">{label}</dt>
    <dd className="whitespace-pre-wrap break-words text-sm leading-relaxed text-stone-800">{children || '—'}</dd>
  </div>
}

