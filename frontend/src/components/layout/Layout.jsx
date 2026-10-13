import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import DemoBanner from './DemoBanner.jsx'
import Footer from './Footer.jsx'
import Header from './Header.jsx'
import WhatsAppLink from './WhatsAppLink.jsx'

/**
 * Estrutura comum a todas as páginas.
 *
 * Numa aplicação de página única o navegador não recarrega ao trocar de tela, então ninguém
 * avisa quem usa leitor de tela ou teclado que o conteúdo mudou. Por isso, a cada troca de
 * página o foco vai para o título (h1) da nova página e a rolagem volta ao topo (WCAG 2.4.3).
 * Se o endereço traz uma âncora (#secao) que existe na página, a rolagem e o foco vão para o título
 * dessa seção. O roteador não faz isso sozinho.
 */
export default function Layout() {
  const location = useLocation()
  const mainRef = useRef(/** @type {HTMLElement | null} */ (null))
  const previousPath = useRef(/** @type {string | null} */ (null))

  // "location.key" muda a cada navegação, inclusive ao clicar de novo no mesmo link de âncora:
  // quem rolou a página para longe e clica outra vez no índice precisa voltar à seção.
  useEffect(() => {
    // Na primeira exibição o foco fica onde o navegador o pôs (topo do documento); só a âncora
    // do endereço (/privacidade#demonstracao) é atendida, porque o navegador não acha a seção
    // sozinho antes de a página ser desenhada.
    const first = previousPath.current === null
    const pathChanged = !first && previousPath.current !== location.pathname
    previousPath.current = location.pathname

    if (location.hash) {
      let id = location.hash.slice(1)
      try {
        id = decodeURIComponent(id)
      } catch {
        /* âncora malformada: usa como veio */
      }
      const section = document.getElementById(id)
      if (section) {
        section.scrollIntoView()
        const heading = section.matches('h1, h2, h3') ? section : section.querySelector('h1, h2, h3')
        const focusable = heading instanceof HTMLElement ? heading : section
        if (!focusable.hasAttribute('tabindex')) focusable.setAttribute('tabindex', '-1')
        focusable.focus({ preventScroll: true })
        return
      }
    }
    if (!pathChanged) return
    window.scrollTo(0, 0)
    const target = mainRef.current?.querySelector('h1') ?? mainRef.current
    if (target instanceof HTMLElement) target.focus({ preventScroll: true })
  }, [location.key, location.pathname, location.hash])

  return (
    <>
      <a
        className="skip-link"
        href="#conteudo"
        onClick={(event) => {
          event.preventDefault()
          mainRef.current?.focus()
          mainRef.current?.scrollIntoView()
        }}
      >
        Ir para o conteúdo
      </a>
      <DemoBanner />
      <Header />
      <main id="conteudo" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <Footer />
      <WhatsAppLink />
    </>
  )
}
