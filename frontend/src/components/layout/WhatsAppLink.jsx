import { useState } from 'react'
import { useServices } from '../../state/services.jsx'
import Button from '../ui/Button.jsx'
import Dialog from '../ui/Dialog.jsx'
import Icon from '../ui/Icon.jsx'

const WA_ME = 'https://wa.me/'

/** @param {string} number @param {string} [text] */
const waLink = (number, text) => `${WA_ME}${number}${text ? `?text=${encodeURIComponent(text)}` : ''}`

const ICON = <Icon name="whatsapp" size={56} viewBox="3 2.75 18 18" />

/**
 * Botão fixo que leva ao chatbot do Apura no WhatsApp.
 *
 * No sandbox da Twilio, a conversa só funciona depois que a pessoa envia o código "join …". Sem
 * aviso, ela veria a mensagem pronta, apagaria e colaria a notícia, e o chatbot não responderia.
 * Por isso o botão abre antes uma janela que explica o passo (Nielsen: ajudar a pessoa a não errar)
 * e um link com o código já escrito. Com um número oficial (sem código), abre direto a conversa.
 */
export default function WhatsAppLink() {
  const { config } = useServices()
  const { number, joinCode } = config.whatsapp
  const [open, setOpen] = useState(false)

  if (!joinCode) {
    return (
      <a
        className="whatsapp-link"
        href={waLink(number)}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Verificar pelo WhatsApp (abre em uma nova aba)"
        title="Verificar pelo WhatsApp"
      >
        {ICON}
      </a>
    )
  }

  return (
    <>
      <button
        type="button"
        className="whatsapp-link"
        aria-haspopup="dialog"
        aria-label="Verificar pelo WhatsApp"
        title="Verificar pelo WhatsApp"
        onClick={() => setOpen(true)}
      >
        {ICON}
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        eyebrow="Antes da primeira notícia"
        title="Use o Apura no WhatsApp"
        actions={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Agora não
            </Button>
            <Button href={waLink(number, joinCode)} external icon="whatsapp" data-autofocus onClick={() => setOpen(false)}>
              Abrir o WhatsApp
            </Button>
          </>
        }
      >
        <ol className="whatsapp-steps">
          <li>
            Toque em <strong>Abrir o WhatsApp</strong>. A conversa abre com esta mensagem já escrita:{' '}
            <code className="whatsapp-code">{joinCode}</code>
          </li>
          <li>
            <strong>Envie essa mensagem sem mudar nada.</strong> Ela libera o Apura para o seu número, e você recebe
            uma confirmação.
          </li>
          <li>
            Depois, <strong>cole o texto ou o link da notícia</strong> e envie.
          </li>
        </ol>
        <p className="whatsapp-note">
          O passo da mensagem só é preciso na primeira vez, ou se você ficar mais de 3 dias sem usar. Se a mensagem
          não aparecer escrita, digite-a exatamente como acima.
        </p>
      </Dialog>
    </>
  )
}
