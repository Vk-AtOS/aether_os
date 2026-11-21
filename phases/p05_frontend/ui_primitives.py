"""P05 Frontend: dependency-free shadcn-style UI primitives (plain React + Tailwind classes).

Model-written pages import `components/ui/<name>` the way shadcn projects do, but the generator never wrote
those files, so `vite build` died with ENOENT. missing_modules.py writes these on demand.
UI_PRIMITIVES maps module name -> (TSX source, default export). Exported names are read from the source.
"""
from __future__ import annotations

_H = "import * as React from 'react'\n\n"
_CN = "const cx = (...a: Array<string | undefined | false>) => a.filter(Boolean).join(' ')\n\n"


def _div(name: str, cls: str, tag: str = "div", attrs: str = "HTMLDivElement") -> str:
    return (f"export const {name} = React.forwardRef<{attrs}, React.HTMLAttributes<{attrs}>>(\n"
            f"  ({{ className, ...props }}, ref) => <{tag} ref={{ref as any}} className={{cx('{cls}', className)}} {{...props}} />\n)\n"
            f"{name}.displayName = '{name}'\n\n")


_CARD = _H + _CN + (
    _div("Card", "rounded-lg border border-gray-200 bg-white text-gray-900 shadow-sm dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100")
    + _div("CardHeader", "flex flex-col space-y-1.5 p-6")
    + _div("CardTitle", "text-lg font-semibold leading-none tracking-tight", "h3", "HTMLHeadingElement")
    + _div("CardDescription", "text-sm text-gray-500 dark:text-gray-400", "p", "HTMLParagraphElement")
    + _div("CardContent", "p-6 pt-0")
    + _div("CardFooter", "flex items-center p-6 pt-0"))

_BUTTON = _H + _CN + """\
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: string
  size?: string
  asChild?: boolean
}

const variants: Record<string, string> = {
  default: 'bg-blue-600 text-white hover:bg-blue-700',
  destructive: 'bg-red-600 text-white hover:bg-red-700',
  outline: 'border border-gray-300 bg-transparent hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700',
  secondary: 'bg-gray-100 text-gray-900 hover:bg-gray-200',
  ghost: 'bg-transparent hover:bg-gray-100 dark:hover:bg-gray-700',
  link: 'bg-transparent text-blue-600 underline-offset-4 hover:underline',
}
const sizes: Record<string, string> = { default: 'h-10 px-4 py-2', sm: 'h-9 px-3', lg: 'h-11 px-8', icon: 'h-10 w-10' }

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', asChild: _asChild, ...props }, ref) => (
    <button
      ref={ref}
      className={cx('inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50', variants[variant] || variants.default, sizes[size] || sizes.default, className)}
      {...props}
    />
  )
)
Button.displayName = 'Button'
export const buttonVariants = (o?: { variant?: string; size?: string; className?: string }) =>
  cx(variants[o?.variant || 'default'], sizes[o?.size || 'default'], o?.className)
"""

_INPUT = _H + _CN + """\
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, ...props }, ref) => (
    <>
      <input ref={ref} aria-invalid={error ? true : undefined} className={cx('flex h-10 w-full rounded-md border bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50', error ? 'border-red-400' : 'border-gray-300', className)} {...props} />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </>
  )
)
Input.displayName = 'Input'
"""

_LABEL = _H + _CN + """\
export const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => <label ref={ref} className={cx('text-sm font-medium leading-none', className)} {...props} />
)
Label.displayName = 'Label'
"""

_TEXTAREA = _H + _CN + """\
export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: string
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => (
    <>
      <textarea ref={ref} aria-invalid={error ? true : undefined} className={cx('flex min-h-[80px] w-full rounded-md border bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500', error ? 'border-red-400' : 'border-gray-300', className)} {...props} />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </>
  )
)
Textarea.displayName = 'Textarea'
"""

_BADGE = _H + _CN + """\
const variants: Record<string, string> = {
  default: 'bg-blue-600 text-white',
  secondary: 'bg-gray-100 text-gray-900',
  destructive: 'bg-red-600 text-white',
  outline: 'border border-gray-300 text-gray-900',
}

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: string
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return <span className={cx('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold', variants[variant] || variants.default, className)} {...props} />
}
export const badgeVariants = (o?: { variant?: string }) => variants[o?.variant || 'default']
"""

_TABLE = _H + _CN + (
    "export const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(\n"
    "  ({ className, ...props }, ref) => (\n"
    "    <div className=\"relative w-full overflow-auto\"><table ref={ref} className={cx('w-full caption-bottom text-sm', className)} {...props} /></div>\n"
    "  )\n)\nTable.displayName = 'Table'\n\n"
    + _div("TableHeader", "[&_tr]:border-b", "thead", "HTMLTableSectionElement")
    + _div("TableBody", "[&_tr:last-child]:border-0", "tbody", "HTMLTableSectionElement")
    + _div("TableFooter", "border-t font-medium", "tfoot", "HTMLTableSectionElement")
    + _div("TableRow", "border-b transition-colors hover:bg-gray-50", "tr", "HTMLTableRowElement")
    + _div("TableHead", "h-12 px-4 text-left align-middle font-medium text-gray-500", "th", "HTMLTableCellElement")
    + _div("TableCell", "p-4 align-middle", "td", "HTMLTableCellElement")
    + _div("TableCaption", "mt-4 text-sm text-gray-500", "caption", "HTMLTableCaptionElement"))

_SKELETON = _H + _CN + "export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {\n  return <div className={cx('animate-pulse rounded-md bg-gray-200 dark:bg-gray-700', className)} {...props} />\n}\n"

_SEPARATOR = _H + _CN + """\
export function Separator({ className, orientation = 'horizontal', ...props }: React.HTMLAttributes<HTMLDivElement> & { orientation?: 'horizontal' | 'vertical' }) {
  return <div role="separator" className={cx('shrink-0 bg-gray-200', orientation === 'vertical' ? 'h-full w-px' : 'h-px w-full', className)} {...props} />
}
"""

_TABS = _H + _CN + """\
type TabsCtx = { value?: string; set: (v: string) => void }
const Ctx = React.createContext<TabsCtx>({ set: () => {} })

export function Tabs({ value, defaultValue, onValueChange, className, children, ...props }:
  Omit<React.HTMLAttributes<HTMLDivElement>, 'defaultValue'> & { value?: string; defaultValue?: string; onValueChange?: (v: string) => void }) {
  const [inner, setInner] = React.useState(defaultValue)
  const current = value !== undefined ? value : inner
  const set = (v: string) => { setInner(v); onValueChange?.(v) }
  return <Ctx.Provider value={{ value: current, set }}><div className={className} {...props}>{children}</div></Ctx.Provider>
}
export const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} role="tablist" className={cx('inline-flex items-center rounded-md bg-gray-100 p-1', className)} {...props} />
)
TabsList.displayName = 'TabsList'
export function TabsTrigger({ value, className, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { value: string }) {
  const ctx = React.useContext(Ctx)
  const active = ctx.value === value
  return <button type="button" role="tab" aria-selected={active} onClick={() => ctx.set(value)} className={cx('rounded px-3 py-1.5 text-sm font-medium', active ? 'bg-white shadow' : 'text-gray-500', className)} {...props}>{children}</button>
}
export function TabsContent({ value, className, children, ...props }: React.HTMLAttributes<HTMLDivElement> & { value: string }) {
  const ctx = React.useContext(Ctx)
  return ctx.value === value ? <div role="tabpanel" className={cx('mt-2', className)} {...props}>{children}</div> : null
}
"""

_DIALOG = _H + _CN + """\
type DialogCtx = { open: boolean; setOpen: (o: boolean) => void }
const Ctx = React.createContext<DialogCtx>({ open: false, setOpen: () => {} })
type DivProps = React.HTMLAttributes<HTMLDivElement>

export function Dialog({ open, defaultOpen = false, onOpenChange, children }:
  { open?: boolean; defaultOpen?: boolean; onOpenChange?: (o: boolean) => void; children?: React.ReactNode }) {
  const [inner, setInner] = React.useState(defaultOpen)
  const isOpen = open !== undefined ? open : inner
  const setOpen = (o: boolean) => { setInner(o); onOpenChange?.(o) }
  return <Ctx.Provider value={{ open: isOpen, setOpen }}>{children}</Ctx.Provider>
}
export function DialogTrigger({ children, asChild: _a, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = React.useContext(Ctx)
  return <button type="button" onClick={() => ctx.setOpen(true)} {...props}>{children}</button>
}
export function DialogClose({ children, asChild: _a, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = React.useContext(Ctx)
  return <button type="button" onClick={() => ctx.setOpen(false)} {...props}>{children}</button>
}
export function DialogContent({ className, children, ...props }: DivProps) {
  const ctx = React.useContext(Ctx)
  if (!ctx.open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => ctx.setOpen(false)}>
      <div role="dialog" aria-modal="true" className={cx('w-full max-w-lg rounded-lg bg-white p-6 shadow-lg', className)} onClick={(e) => e.stopPropagation()} {...props}>{children}</div>
    </div>
  )
}
export const DialogHeader = ({ className, ...props }: DivProps) => <div className={cx('flex flex-col space-y-1.5', className)} {...props} />
export const DialogFooter = ({ className, ...props }: DivProps) => <div className={cx('flex justify-end gap-2 pt-4', className)} {...props} />
export const DialogTitle = ({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => <h2 className={cx('text-lg font-semibold', className)} {...props} />
export const DialogDescription = ({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => <p className={cx('text-sm text-gray-500', className)} {...props} />
"""

_SELECT = _H + _CN + """\
type SelCtx = { value?: string; set: (v: string) => void; open: boolean; setOpen: (o: boolean) => void }
const Ctx = React.createContext<SelCtx>({ set: () => {}, open: false, setOpen: () => {} })

export function Select({ value, defaultValue, onValueChange, children }:
  { value?: string; defaultValue?: string; onValueChange?: (v: string) => void; children?: React.ReactNode; [k: string]: any }) {
  const [inner, setInner] = React.useState(defaultValue)
  const [open, setOpen] = React.useState(false)
  const current = value !== undefined ? value : inner
  const set = (v: string) => { setInner(v); setOpen(false); onValueChange?.(v) }
  return <Ctx.Provider value={{ value: current, set, open, setOpen }}><div className="relative inline-block">{children}</div></Ctx.Provider>
}
export const SelectGroup = (props: React.HTMLAttributes<HTMLDivElement>) => <div {...props} />
export function SelectValue({ placeholder }: { placeholder?: string }) {
  const ctx = React.useContext(Ctx)
  return <span>{ctx.value || placeholder}</span>
}
export function SelectTrigger({ className, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = React.useContext(Ctx)
  return <button type="button" onClick={() => ctx.setOpen(!ctx.open)} className={cx('flex h-10 w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm', className)} {...props}>{children}</button>
}
export function SelectContent({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const ctx = React.useContext(Ctx)
  if (!ctx.open) return null
  return <div className={cx('absolute z-50 mt-1 min-w-full rounded-md border border-gray-200 bg-white p-1 shadow-md', className)} {...props}>{children}</div>
}
export function SelectItem({ value, className, children, ...props }: Omit<React.HTMLAttributes<HTMLDivElement>, 'value'> & { value: string }) {
  const ctx = React.useContext(Ctx)
  return <div role="option" aria-selected={ctx.value === value} onClick={() => ctx.set(value)} className={cx('cursor-pointer rounded px-2 py-1.5 text-sm hover:bg-gray-100', className)} {...props}>{children}</div>
}
"""

_UTILS = ("export function cn(...inputs: Array<string | false | null | undefined>): string {\n"
          "  return inputs.filter(Boolean).join(' ')\n}\n")

UI_PRIMITIVES: dict[str, tuple[str, str | None]] = {
    "card": (_CARD, "Card"), "button": (_BUTTON, "Button"), "input": (_INPUT, "Input"),
    "label": (_LABEL, "Label"), "textarea": (_TEXTAREA, "Textarea"), "badge": (_BADGE, "Badge"),
    "table": (_TABLE, "Table"), "skeleton": (_SKELETON, "Skeleton"), "separator": (_SEPARATOR, "Separator"),
    "tabs": (_TABS, "Tabs"), "dialog": (_DIALOG, "Dialog"), "select": (_SELECT, "Select"),
}
# Non-ui helper modules shadcn code imports (`@/lib/utils` -> cn).
UTIL_MODULES: dict[str, str] = {"lib/utils": _UTILS, "utils/cn": _UTILS}
