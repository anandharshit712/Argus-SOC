import ArgusLogo from '../components/ArgusLogo.tsx'
import LoginForm from '../components/LoginForm.tsx'
import type { SessionOut } from '../api/apiTypes.ts'
import './LoginPage.css'

type LoginPageProps = { onSignedIn: (session: SessionOut) => void }

export default function LoginPage({ onSignedIn }: LoginPageProps) {
  return (
    <main className="login-page">
      <div className="login-frame">
        <span className="login-version">// ARGUS SOC&nbsp;&nbsp;v1.0</span>

        <section className="login-panel">
          <ArgusLogo size={104} />
          <h1>ARGUS SOC</h1>
          <p className="login-tagline">Smarter detection. Faster response.</p>
          <LoginForm onSignedIn={onSignedIn} />
        </section>

        <aside className="login-scene" aria-hidden="true">
          <svg viewBox="0 0 400 600" preserveAspectRatio="xMidYMax slice">
            <path d="M0 250 L70 190 L130 230 L210 150 L290 215 L340 175 L400 230 V600 H0z" fill="#1a2620" />
            <path d="M0 330 L90 290 L180 320 L260 285 L400 330 V600 H0z" fill="#121c17" />
            <g fill="#0b120f">
              <rect x="70" y="250" width="34" height="200" />
              <rect x="58" y="226" width="58" height="34" />
              <rect x="180" y="380" width="110" height="60" />
              <rect x="250" y="340" width="130" height="80" />
              <rect x="210" y="460" width="190" height="140" />
            </g>
          </svg>
        </aside>
      </div>
    </main>
  )
}
