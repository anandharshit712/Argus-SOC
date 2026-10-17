import { Link } from 'react-router-dom'
import Icon from './Icon.tsx'
import './NotFoundView.css'

type NotFoundViewProps = { message?: string }

// Shown for an unknown route, and by pages when the case or tenant in the URL does not exist.
export default function NotFoundView({
  message = 'The page you’re looking for doesn’t exist or the tenant is not valid.',
}: NotFoundViewProps) {
  return (
    <section className="not-found">
      <svg viewBox="0 0 120 100" width="150" height="125" role="img" aria-label="Broken screen" fill="none" strokeWidth="3">
        <rect x="20" y="8" width="80" height="58" rx="5" stroke="#4ade6a" />
        <path d="M34 26h40M34 38h30M34 50h22" stroke="#4ade6a" strokeLinecap="round" />
        <path d="M50 66v14M70 66v14M38 82h44" stroke="#4ade6a" strokeLinecap="round" />
        <rect x="76" y="44" width="30" height="30" rx="5" fill="#ff6b6b" stroke="none" />
        <path d="M84 52l14 14M98 52L84 66" stroke="#fff" strokeLinecap="round" />
      </svg>
      <p className="not-found-code">404</p>
      <h1>Page Not Found</h1>
      <p className="not-found-text">{message}</p>
      <Link to="/cases" className="not-found-link">
        Back to Cases <Icon name="arrowRight" size={20} />
      </Link>
    </section>
  )
}
