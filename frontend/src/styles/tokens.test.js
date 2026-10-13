import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Guarda do sistema de design: lê tokens.css e confere, a cada alteração, o que os requisitos
// pedem de legibilidade e de alvo de toque (RNF08: WCAG 2.2 AA, alvos de 48 × 48 px).
// Se alguém trocar uma cor (por exemplo, ao aplicar os valores do Figma), este teste diz se o par
// de cores continua legível.

// Caminhos em texto (e não URL): no ambiente jsdom, "URL" é a do navegador e o Node não a aceita para ler arquivos.
const dir = dirname(fileURLToPath(import.meta.url))
const read = (name) => readFileSync(join(dir, name), 'utf8')
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

// ---- Leitura dos tokens ---------------------------------------------------------------------

const tokensCss = stripComments(read('tokens.css'))
const rootBlock = tokensCss.match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''

/** @type {Map<string, string>} */
const raw = new Map()
for (const match of rootBlock.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) raw.set(match[1], match[2].trim())

/** Resolve var(--x) recursivamente. */
function resolve(name, seen = new Set()) {
  if (seen.has(name)) throw new Error(`Referência circular em ${name}`)
  const value = raw.get(name)
  if (value === undefined) throw new Error(`Token inexistente: ${name}`)
  const inner = value.match(/^var\((--[\w-]+)\)$/)
  return inner ? resolve(inner[1], new Set([...seen, name])) : value
}

// ---- Contraste (WCAG 2.x) -------------------------------------------------------------------

function parseColor(text) {
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join('') : hex[1]
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 }
  }
  const fn = text.match(/^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+))?\s*\)$/)
  if (fn) return { r: +fn[1], g: +fn[2], b: +fn[3], a: fn[4] === undefined ? 1 : +fn[4] }
  throw new Error(`Cor não reconhecida: ${text}`)
}

function luminance({ r, g, b }) {
  const channel = (v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

const color = (token) => parseColor(resolve(`--${token}`))

function contrast(foreground, background) {
  const l1 = luminance(color(foreground))
  const l2 = luminance(color(background))
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}

const TEXT_MIN = 4.5 // WCAG 1.4.3, texto até 24 px (ou 18,66 px em negrito)
const UI_MIN = 3 // WCAG 1.4.11, contornos de controles, ícones e anel de foco

describe('o leitor de tokens', () => {
  it('lê os tokens e resolve as referências (sanidade do próprio teste)', () => {
    expect(raw.size).toBeGreaterThan(100)
    expect(resolve('--color-text')).toBe('#08213c')
    expect(resolve('--color-bg')).toBe('#f7f5ef')
  })

  it('o cálculo de contraste bate com valores conhecidos', () => {
    expect(contrast('white', 'navy-900')).toBeGreaterThan(15)
    expect(contrast('white', 'white')).toBeCloseTo(1, 5)
    // preto sobre branco = 21:1 (referência da própria WCAG)
    expect((luminance({ r: 255, g: 255, b: 255 }) + 0.05) / (luminance({ r: 0, g: 0, b: 0 }) + 0.05)).toBeCloseTo(21, 5)
  })

  it('todo var() usado em tokens.css aponta para um token que existe', () => {
    for (const [name, value] of raw) {
      for (const ref of value.matchAll(/var\((--[\w-]+)\)/g)) {
        expect(raw.has(ref[1]), `${name} usa ${ref[1]}, que não existe`).toBe(true)
      }
    }
  })
})

describe('contraste de texto (WCAG 1.4.3, mínimo 4,5:1)', () => {
  const SURFACES = ['color-bg', 'color-surface', 'color-surface-muted', 'color-surface-quiet']

  it.each(SURFACES)('texto principal sobre %s', (surface) => {
    expect(contrast('color-text', surface)).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  it.each(SURFACES)('texto de apoio sobre %s', (surface) => {
    expect(contrast('color-text-muted', surface)).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  it.each(['color-bg', 'color-surface'])('texto dourado (destaque) sobre %s', (surface) => {
    expect(contrast('color-text-accent', surface)).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  it('texto de exemplo (placeholder) sobre o fundo do campo', () => {
    expect(contrast('color-text-placeholder', 'color-surface')).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  it.each(['color-text-on-dark', 'color-text-on-dark-soft', 'color-text-on-dark-muted', 'color-text-on-dark-accent'])(
    '%s sobre o azul-marinho',
    (foreground) => {
      expect(contrast(foreground, 'color-surface-dark')).toBeGreaterThanOrEqual(TEXT_MIN)
    },
  )

  it.each([
    ['color-on-primary', 'color-primary'],
    ['color-on-primary', 'color-primary-hover'],
    ['color-on-accent', 'color-accent'],
    ['color-on-accent', 'color-accent-hover'],
    ['color-on-danger', 'color-danger'],
    ['color-on-danger', 'color-danger-hover'],
    ['color-on-whatsapp', 'color-whatsapp'],
    ['color-on-whatsapp', 'color-whatsapp-hover'],
  ])('%s sobre %s (botões, em repouso e ao passar o mouse)', (foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(TEXT_MIN)
  })

  describe('status do resultado (RF16): texto e ícone sobre o próprio fundo e sobre as superfícies', () => {
    const TONES = ['low', 'attention', 'high', 'inconclusive', 'info', 'success', 'warning', 'error']

    it.each(TONES)('%s: tom sobre o próprio fundo', (tone) => {
      expect(contrast(`tone-${tone}-fg`, `tone-${tone}-bg`)).toBeGreaterThanOrEqual(TEXT_MIN)
    })

    it.each(TONES.flatMap((tone) => ['color-surface', 'color-bg'].map((surface) => [tone, surface])))(
      '%s: tom sobre %s',
      (tone, surface) => {
        expect(contrast(`tone-${tone}-fg`, surface)).toBeGreaterThanOrEqual(TEXT_MIN)
      },
    )
  })
})

describe('contraste de elementos de interface (WCAG 1.4.11, mínimo 3:1)', () => {
  it.each(['color-surface', 'color-bg', 'color-surface-muted'])('contorno de campo e controle sobre %s', (surface) => {
    expect(contrast('color-border-control', surface)).toBeGreaterThanOrEqual(UI_MIN)
  })

  it.each(['color-bg', 'color-surface', 'color-surface-muted', 'color-surface-quiet'])(
    'anel de foco sobre %s (a camada azul-marinho aparece sobre fundo claro)',
    (surface) => {
      expect(contrast('color-focus-outer', surface)).toBeGreaterThanOrEqual(UI_MIN)
    },
  )

  it('anel de foco sobre o azul-marinho (a camada dourada aparece sobre fundo escuro)', () => {
    expect(contrast('color-focus-inner', 'color-surface-dark')).toBeGreaterThanOrEqual(UI_MIN)
  })

  it('o anel de foco tem pelo menos 2 px (WCAG 2.4.11/2.4.13) e deslocamento', () => {
    expect(parseFloat(resolve('--focus-outline-width'))).toBeGreaterThanOrEqual(2)
    expect(parseFloat(resolve('--focus-inner-width'))).toBeGreaterThanOrEqual(2)
  })
})

describe('tamanhos e proporções', () => {
  const rem = (name) => parseFloat(resolve(name))

  it('alvo de toque mínimo é 48 px (RNF08), com a fonte-base de 16 px', () => {
    expect(resolve('--target-min')).toMatch(/rem$/)
    expect(rem('--target-min') * 16).toBeGreaterThanOrEqual(48)
  })

  it('o texto nunca é menor que 15 px, exceto o rótulo em caixa alta e negrito', () => {
    expect(rem('--text-small') * 16).toBeGreaterThanOrEqual(15)
    expect(rem('--text-ui') * 16).toBeGreaterThanOrEqual(16)
    expect(rem('--text-body') * 16).toBeGreaterThanOrEqual(16)
    expect(rem('--text-label') * 16).toBeGreaterThanOrEqual(12)
  })

  it('as fontes são medidas em rem (respeitam o tamanho escolhido no navegador, WCAG 1.4.4)', () => {
    for (const name of ['--text-label', '--text-small', '--text-ui', '--text-body', '--text-lead', '--text-h4', '--text-h3', '--text-h2']) {
      expect(resolve(name), name).toMatch(/rem$/)
    }
    for (const name of ['--text-h1', '--text-display']) expect(resolve(name), name).toMatch(/^clamp\(.*rem/)
  })

  it('entrelinha do corpo ≥ 1,5 (WCAG 1.4.12) e medida de leitura entre 45 e 75 caracteres', () => {
    expect(parseFloat(resolve('--leading-body'))).toBeGreaterThanOrEqual(1.5)
    const measure = parseFloat(resolve('--measure'))
    expect(measure).toBeGreaterThanOrEqual(45)
    expect(measure).toBeLessThanOrEqual(75)
  })

  it('a escala de espaço é múltipla de 4 px (base de 4)', () => {
    for (const name of [...raw.keys()].filter((key) => /^--space-\d+$/.test(key))) {
      const px = rem(name) * 16
      expect(px % 4, `${name} = ${px}px`).toBe(0)
    }
  })

  it('o corpo do texto não encolhe abaixo de 16 px em telas pequenas', () => {
    const small = tokensCss.match(/@media \(max-width: 32\.5em\)\s*\{\s*:root\s*\{([^}]*)\}/)?.[1] ?? ''
    const body = small.match(/--text-body:\s*([\d.]+)rem/)?.[1]
    expect(body).toBeDefined()
    expect(parseFloat(body) * 16).toBeGreaterThanOrEqual(16)
  })
})

describe('pontos de quebra', () => {
  // Em consultas de mídia, "em" é o tamanho de fonte padrão do navegador (o que a pessoa escolheu), não
  // o da página. Com "px", quem aumenta a fonte padrão ficaria com o layout de tela grande e
  // letras enormes (rolagem horizontal, WCAG 1.4.4 e 1.4.10). Com "em", o layout estreito entra antes.
  const sheets = readdirSync(dir).filter((name) => name.endsWith('.css'))

  it('toda consulta de largura usa em, nunca px', () => {
    for (const name of sheets) {
      const css = stripComments(read(name))
      for (const match of css.matchAll(/@media[^{]*\((?:min|max)-width:\s*([^)]+)\)/g)) {
        expect(match[1].trim(), `${name}: ${match[0]}`).toMatch(/^[\d.]+em$/)
      }
    }
  })

  it('os pontos de quebra são os esperados (312, 380, 520, 780, 1000 e 1500 px com fonte de 16 px)', () => {
    const used = new Set()
    for (const name of sheets) {
      for (const match of stripComments(read(name)).matchAll(/\((?:min|max)-width:\s*([\d.]+)em\)/g)) used.add(parseFloat(match[1]) * 16)
    }
    expect([...used].sort((a, b) => a - b)).toEqual([312, 380, 520, 780, 1000, 1500])
  })
})

describe('uso dos tokens nos demais arquivos CSS', () => {
  const files = readdirSync(dir).filter((name) => name.endsWith('.css') && name !== 'tokens.css')
  const sources = Object.fromEntries(files.map((name) => [name, stripComments(read(name))]))

  it('há os arquivos esperados', () => {
    expect(files.sort()).toEqual(['base.css', 'components.css', 'index.css', 'layout.css', 'pages.css'])
  })

  it.each(files)('%s não escreve cor à mão: tudo vem de tokens.css', (name) => {
    expect(sources[name].match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\bcolor\(/g) ?? []).toEqual([])
  })

  it.each(files)('%s usa só nomes de cor e de espaço que existem nos tokens', (name) => {
    for (const ref of sources[name].matchAll(/var\((--[\w-]+)/g)) {
      const known = raw.has(ref[1]) || /^--(stack-gap|cluster-gap|value|at|columns|min|gap|i|n|delay)\b/.test(ref[1])
      // Propriedades locais (definidas no próprio CSS ou por "style" no JSX) também são aceitas.
      const defined = new RegExp(`${ref[1]}\\s*:`).test(sources[name]) || Object.values(sources).some((css) => new RegExp(`${ref[1]}\\s*:`).test(css))
      expect(known || defined, `${name} usa ${ref[1]}`).toBe(true)
    }
  })

  it.each(files)('%s escolhe o tamanho da fonte só entre os tokens', (name) => {
    const literal = [...sources[name].matchAll(/font-size:\s*([^;]+);/g)].map((m) => m[1].trim()).filter((value) => !/^(var\(--text-[\w-]+\)|inherit|1em)$/.test(value))
    expect(literal).toEqual([])
  })

  it('a fonte de 12 px (--text-label) só aparece em rótulos em caixa alta e negrito', () => {
    const offenders = []
    for (const [name, css] of Object.entries(sources)) {
      for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const [, selector, body] = rule
        if (!/font-size:\s*var\(--text-label\)/.test(body)) continue
        const upper = /text-transform:\s*uppercase/.test(body)
        const bold = /font-weight:\s*(var\(--weight-bold\)|700|bold)/.test(body)
        if (!upper || !bold) offenders.push(`${name}: ${selector.trim().replace(/\s+/g, ' ')}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('respeita quem pede menos movimento e quem usa cores forçadas', () => {
    expect(sources['base.css']).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
    expect(sources['base.css']).toMatch(/@media \(forced-colors: active\)/)
  })

  it('nenhum arquivo desliga o contorno de foco de controles (só dos alvos programáticos tabindex="-1")', () => {
    const offenders = []
    for (const [name, css] of Object.entries(sources)) {
      for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
        const [, selector, body] = rule
        if (/outline:\s*(none|0)\b/.test(body) && !/tabindex=['"]?-1['"]?/.test(selector) && !/:focus-visible/.test(selector.replace(/:not\(:focus-visible\)/g, ''))) {
          offenders.push(`${name}: ${selector.trim().replace(/\s+/g, ' ')}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
