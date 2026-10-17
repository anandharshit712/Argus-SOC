type ArgusLogoProps = { size?: number }

// Inverted-triangle shield with an eye-like cut-out, drawn inline so it follows the theme colour.
export default function ArgusLogo({ size = 96 }: ArgusLogoProps) {
  return (
    <svg
      width={size}
      height={size * 0.82}
      viewBox="0 0 120 98"
      role="img"
      aria-label="Argus SOC logo"
      fill="currentColor"
    >
      <path d="M0 0h50L38 14 60 52 82 14 70 0h50L60 98 0 0z" opacity="0.95" />
      <path d="M44 22l16 28 16-28-8-8H52l-8 8z" fill="var(--bg)" opacity="0.85" />
      <circle cx="60" cy="30" r="6" />
    </svg>
  )
}
