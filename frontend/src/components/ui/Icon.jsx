// Ícones de traço (24 × 24), herdados do protótipo v2, mais os de status e de ação que a
// aplicação real precisa. Todos são decorativos (aria-hidden): o significado está sempre no
// texto ao lado, nunca só no desenho (WCAG 1.4.1, 1.1.1).

const PATHS = {
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  back: <path d="M20 12H4m6-6-6 6 6 6" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  link: <path d="m10 13 4-4m-6 8-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2-1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" />,
  text: <path d="M4 5h16M12 5v15M8 20h8M4 5v3m16-3v3" />,
  check: <path d="m5 12 4 4L19 6" />,
  shield: (
    <>
      <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  eye: (
    <>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  'eye-off': (
    <>
      <path d="M3 3l18 18" />
      <path d="M10.6 6.1A10 10 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3.2 3.9M6.5 7.6C3.9 9.3 2 12 2 12s4 6 10 6a9.7 9.7 0 0 0 4-.9" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 6 9 7 9-7" />
    </>
  ),
  whatsapp: (
    <>
      <path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4.1A8 8 0 1 1 20 11.5Z" />
      <path d="M8.5 8.5c.3-.5.6-.5.9-.4l.8 1.7c.1.3.1.5-.1.7l-.5.5c.5 1 1.3 1.8 2.3 2.3l.5-.5c.2-.2.4-.2.7-.1l1.7.8c.3.1.3.5.2.8-.2.6-.7 1-1.3 1.1-1.1.1-2.7-.7-3.9-1.9s-2-2.8-1.9-3.9c.1-.5.4-.9.6-1.1Z" />
    </>
  ),
  document: (
    <>
      <path d="M14 3H5v18h14V8l-5-5Z" />
      <path d="M14 3v5h5M8 12h8m-8 4h6" />
    </>
  ),
  external: (
    <>
      <path d="M14 3h7v7m0-7L10 14" />
      <path d="M10 3H3v18h18v-7" />
    </>
  ),
  trash: <path d="M3 6h18m-13 0V3h8v3M5 6l1 15h12l1-15M10 10v6m4-6v6" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6m0-10h.01" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21v-3a8 8 0 0 1 16 0v3" />
    </>
  ),
  up: <path d="M7 10v11H3V10h4Zm0 2 5-9h3v6h6l-2 12H7" />,
  down: <path d="M7 14V3H3v11h4Zm0-2 5 9h3v-6h6L19 3H7" />,
  lock: (
    <>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  undo: <path d="M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3" />,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  // Status do resultado: forma externa + símbolo diferentes, para não depender só de cor.
  'status-low': (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  'status-attention': (
    <>
      <path d="M12 3 2.5 20h19L12 3Z" />
      <path d="M12 10v4m0 3h.01" />
    </>
  ),
  'status-high': (
    <>
      <path d="M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2L8.2 3Z" />
      <path d="m9 9 6 6m0-6-6 6" />
    </>
  ),
  'status-inconclusive': (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01" />
    </>
  ),
}

/**
 * @param {{ name: keyof typeof PATHS, size?: number, className?: string }} props
 */
export default function Icon({ name, size = 20, className = 'icon' }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name] ?? PATHS.info}
    </svg>
  )
}
