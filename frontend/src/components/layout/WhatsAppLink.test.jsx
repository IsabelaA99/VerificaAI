import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { createTestServices, renderWithApp } from '../../test/render.jsx'
import WhatsAppLink from './WhatsAppLink.jsx'

const renderLink = (env = {}) => renderWithApp(<WhatsAppLink />, { services: createTestServices({ env }) })

describe('WhatsAppLink no sandbox (com código "join")', () => {
  it('o botão abre uma janela que explica o envio do código antes da notícia', async () => {
    renderLink()
    await userEvent.click(screen.getByRole('button', { name: 'Verificar pelo WhatsApp' }))

    const dialog = screen.getByRole('dialog', { name: 'Use o Apura no WhatsApp' })
    expect(within(dialog).getByText('join division-facing')).toBeInTheDocument()
    expect(within(dialog).getByText('Envie essa mensagem sem mudar nada.')).toBeInTheDocument()
    expect(within(dialog).getByText('cole o texto ou o link da notícia')).toBeInTheDocument()
  })

  it('o link da janela abre a conversa com o código já escrito, em nova aba', async () => {
    renderLink()
    await userEvent.click(screen.getByRole('button', { name: 'Verificar pelo WhatsApp' }))

    const link = screen.getByRole('link', { name: /Abrir o WhatsApp/ })
    expect(link).toHaveAttribute('href', 'https://wa.me/14155238886?text=join%20division-facing')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveFocus() // a ação principal recebe o foco
  })

  it('usa o número e o código da configuração', async () => {
    renderLink({ VITE_WHATSAPP_NUMBER: '+1 415 000 0000', VITE_WHATSAPP_JOIN_CODE: 'join outra-conta' })
    await userEvent.click(screen.getByRole('button', { name: 'Verificar pelo WhatsApp' }))

    expect(screen.getByRole('link', { name: /Abrir o WhatsApp/ })).toHaveAttribute(
      'href',
      'https://wa.me/14150000000?text=join%20outra-conta',
    )
  })

  it('"Agora não" fecha a janela', async () => {
    renderLink()
    await userEvent.click(screen.getByRole('button', { name: 'Verificar pelo WhatsApp' }))
    await userEvent.click(screen.getByRole('button', { name: 'Agora não' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('sem problemas de acessibilidade com a janela aberta', async () => {
    const { container } = renderLink()
    await userEvent.click(screen.getByRole('button', { name: 'Verificar pelo WhatsApp' }))

    expect(await axe(container)).toHaveNoViolations()
  })
})

describe('WhatsAppLink com número oficial (sem código)', () => {
  it('abre direto a conversa, sem janela', () => {
    renderLink({ VITE_WHATSAPP_NUMBER: '5511333344444', VITE_WHATSAPP_JOIN_CODE: '' })

    const link = screen.getByRole('link', { name: /Verificar pelo WhatsApp/ })
    expect(link).toHaveAttribute('href', 'https://wa.me/5511333344444')
    expect(screen.queryByRole('button', { name: 'Verificar pelo WhatsApp' })).not.toBeInTheDocument()
  })
})
