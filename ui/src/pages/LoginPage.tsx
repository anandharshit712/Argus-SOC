import ArgusLogo from '../components/ArgusLogo.tsx'
import GradientASCII from '../components/GradientASCII.tsx'
import LoginForm from '../components/LoginForm.tsx'
import StarBorder from '../components/StarBorder.tsx'
import TextType from '../components/TextType.tsx'
import type { SessionOut } from '../api/apiTypes.ts'
import './LoginPage.css'

type LoginPageProps = { onSignedIn: (session: SessionOut) => void }

export default function LoginPage({ onSignedIn }: LoginPageProps) {
  return (
    <main className="login-page">
      <div className="login-backdrop" aria-hidden="true">
        <GradientASCII
          colors={['#0a2e18', '#1a6b3a', '#2fa852', '#4ade6a']}
          shape="horizon"
          characters=" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
          cellSize={18}
          density={0.85}
          glyphOpacity={0.8}
          glow={0.25}
          flicker={0.15}
          softness={0.55}
          flow={0.35}
          speed={0.8}
          gradientOpacity={0.75}
          grain={0.05}
          mouseInteraction
          scrambleRadius={0.1}
          clickEffect="wave"
          intro
        />
      </div>
      <StarBorder
        className="login-frame"
        color="#c8ffd6"
        trailColor="#4ade6a"
        duration={10}
        direction="clockwise"
        stars={1}
        trailLength={0.18}
        thickness={1}
        borderWidth={2}
        radius={8}
        glow={0.4}
        hover="none"
        clickPulse
        theme="dark"
      >
        <TextType
          className="login-version"
          prefix="// "
          text={['ARGUS SOC\u00a0\u00a0v1.0', 'THREAT GRAPH ONLINE', 'AWAITING OPERATOR AUTH']}
          typingSpeed={75}
          pauseDuration={1800}
          deletingSpeed={40}
          deleteMode="backspace"
          typeEffect="none"
          mistakes={0}
          cursorStyle="underscore"
          cursorGlide
          showCursor
          cursorBlinkDuration={0.5}
          cursorCharacter="_"
        />

        <section className="login-panel">
          <ArgusLogo size={104} />
          <h1>ARGUS SOC</h1>
          <p className="login-tagline">Smarter detection. Faster response.</p>
          <StarBorder
            className="login-form-shell"
            color="#c8ffd6"
            trailColor="#4ade6a"
            duration={5}
            direction="counterclockwise"
            stars={1}
            trailLength={0.3}
            thickness={1}
            radius={10}
            glow={0.4}
            hover="none"
            clickPulse
            theme="dark"
          >
            <LoginForm onSignedIn={onSignedIn} />
          </StarBorder>
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
      </StarBorder>
    </main>
  )
}
