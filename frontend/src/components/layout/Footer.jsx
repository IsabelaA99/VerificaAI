import { Link } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.js'
import Button from '../ui/Button.jsx'
import Brand from './Brand.jsx'

export default function Footer() {
  const { available } = useAuth()
  return (
    <footer className="site-footer">
      <div className="wrap site-footer__row">
        <div className="site-footer__left">
          <Brand />
          <p>
            Um segundo olhar faz diferença.
            <br />
            Projeto acadêmico · Residência em IA
          </p>
        </div>
        <nav className="site-footer__links" aria-label="Navegação secundária">
          <Link to="/como-funciona">Como funciona</Link>
          <Link to="/privacidade">Privacidade</Link>
          {available ? <Link to="/conta">Minha conta</Link> : null}
          <Button
            href="https://wa.me/5511999999999"
            external
            variant="soft"
            size="small"
            icon="whatsapp"
          >
            Verificar pelo WhatsApp
          </Button>
        </nav>
      </div>
    </footer>
  )
}
