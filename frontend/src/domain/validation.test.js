import { describe, expect, it } from 'vitest'
import { TEXT_LIMITS } from './limits.js'
import { validateInput, validateText, validateUrl } from './validation.js'

const chars = (n) => 'a'.repeat(n)

describe('validateText (RF01: de 50 a 5.000 caracteres)', () => {
  it.each([
    'https://noticias.uol.com.br/colunas/thais-bilenky/2026/10/14/ia-da-meta-bandeira-lula-e-flavio-bolsonaro.htm',
    '  HTTPS://exemplo.com/noticia\n',
    'www.exemplo.com/noticia',
  ])('recusa endereço sozinho como texto: %s', (url) => {
    expect(validateText(url)).toMatchObject({ ok: false, code: 'url_in_text', field: 'text' })
  })

  it('aceita texto de notícia que inclui um link de referência', () => {
    expect(validateText('A prefeitura anunciou novos horários para o transporte coletivo. Fonte: https://exemplo.com')).toMatchObject({ ok: true })
  })

  it('recusa vazio e só espaços como entrada vazia', () => {
    for (const raw of ['', '   ', '\n\n\t']) {
      const result = validateText(raw)
      expect(result).toMatchObject({ ok: false, scenario: 'text_insufficient', code: 'empty_input', field: 'text' })
    }
  })

  it('recusa 49 caracteres e aceita 50 (limite inferior sem lacuna)', () => {
    expect(validateText(chars(TEXT_LIMITS.min - 1))).toMatchObject({
      ok: false,
      scenario: 'text_insufficient',
      code: 'text_too_short',
      details: { length: 49, min_chars: 50 },
    })
    expect(validateText(chars(TEXT_LIMITS.min))).toMatchObject({ ok: true, length: 50 })
  })

  it('aceita o limite máximo e recusa excedente sem cortar o texto', () => {
    expect(validateText(chars(TEXT_LIMITS.max))).toMatchObject({ ok: true, length: TEXT_LIMITS.max })
    const tooLong = validateText(chars(TEXT_LIMITS.max + 1))
    expect(tooLong).toMatchObject({
      ok: false,
      scenario: 'text_too_long',
      details: { length: TEXT_LIMITS.max + 1, max_chars: TEXT_LIMITS.max },
    })
  })

  it('conta depois da normalização, como o servidor', () => {
    // 60 "a" com muitos espaços e linhas em branco ao redor: continua 60 depois de normalizar.
    const padded = `   \n\n\n${chars(60)}\n\n\n   `
    expect(validateText(padded)).toMatchObject({ ok: true, length: 60, value: chars(60) })
    // Espaços repetidos não inflam a contagem.
    const spaced = Array.from({ length: 30 }, () => 'a').join('      ')
    expect(validateText(spaced)).toMatchObject({ ok: true, length: 59 })
  })

  it('conta emoji como um caractere', () => {
    expect(validateText('😀'.repeat(50))).toMatchObject({ ok: true, length: 50 })
  })

  it('devolve o texto normalizado para ser enviado', () => {
    const result = validateText(`  ${chars(60)}  \r\n`)
    expect(result).toMatchObject({ ok: true, value: chars(60) })
  })
})

describe('validateUrl (RF01: HTTP ou HTTPS)', () => {
  it.each(['https://g1.globo.com/politica/noticia/2026/10/08/exemplo.ghtml', 'http://exemplo.com/a?b=1#c', '  https://exemplo.com  '])(
    'aceita %s',
    (raw) => {
      expect(validateUrl(raw)).toMatchObject({ ok: true })
    },
  )

  it('recusa vazio', () => {
    expect(validateUrl('   ')).toMatchObject({ ok: false, scenario: 'invalid_url', field: 'url', details: { reason: 'empty' } })
  })

  it('recusa endereço sem começo (http:// ou https://)', () => {
    expect(validateUrl('g1.globo.com/noticia')).toMatchObject({ ok: false, details: { reason: 'no_scheme' } })
  })

  it.each(['ftp://exemplo.com/arquivo', 'javascript:alert(1)', 'data:text/html,<b>x</b>', 'file:///etc/passwd'])(
    'recusa o protocolo de %s',
    (raw) => {
      expect(validateUrl(raw)).toMatchObject({ ok: false, details: { reason: 'scheme' } })
    },
  )

  it('recusa espaços no meio e endereço longo demais', () => {
    expect(validateUrl('https://exemplo.com/a b')).toMatchObject({ ok: false, details: { reason: 'malformed' } })
    expect(validateUrl(`https://exemplo.com/${chars(2048)}`)).toMatchObject({ ok: false, details: { reason: 'too_long' } })
  })
})

describe('validateInput (RF24: só a opção escolhida é considerada)', () => {
  it('no modo texto ignora o link preenchido', () => {
    expect(validateInput({ inputType: 'text', text: chars(60), url: 'lixo' })).toMatchObject({ ok: true })
  })

  it('no modo link ignora o texto preenchido', () => {
    expect(validateInput({ inputType: 'url', text: chars(60), url: 'lixo' })).toMatchObject({ ok: false, field: 'url' })
    expect(validateInput({ inputType: 'url', text: '', url: 'https://exemplo.com' })).toMatchObject({ ok: true })
  })
})
