const PATHS = {
  home: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  cases: 'M5 4h14v16H5zM5 9h14M9 4v3M15 4v3',
  playbooks: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4.4 3.6-7 8-7s8 2.6 8 7',
  building: 'M5 21V4h9v17M14 9h5v12M8 8h3M8 12h3M8 16h3M3 21h18',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 6l6 6-6 6',
  chevronUp: 'M6 15l6-6 6 6',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  chevronLeft:'M15 6l-6 6 6 6',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-5-5',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  flat: 'M5 12h14',
  pause: 'M8 5v14M16 5v14',
  check: 'M5 12l5 5 9-10',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
} as const

export type IconName = keyof typeof PATHS

type IconProps = { name: IconName; size?: number }

export default function Icon({ name, size = 20 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
