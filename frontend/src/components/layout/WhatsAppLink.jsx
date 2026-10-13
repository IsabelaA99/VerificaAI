import Icon from '../ui/Icon.jsx'

export default function WhatsAppLink() {
  return (
    <a
      className="whatsapp-link"
      href="https://wa.me/5511999999999"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Verificar pelo WhatsApp (abre em uma nova aba)"
      title="Verificar pelo WhatsApp"
    >
      <Icon name="whatsapp" size={56} viewBox="3 2.75 18 18" />
    </a>
  )
}
