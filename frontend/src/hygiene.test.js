import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Higiene do código-fonte (RNF16 e requisitos de entrada de texto):
//   - nada que injete HTML ou execute texto como código;
//   - armazenamento do navegador e rede passam por um único módulo cada, para o que a página
//     de Privacidade descreve ser, de fato, tudo o que acontece;
//   - nenhum segredo; só o link externo do WhatsApp é permitido; nenhum nome antigo do produto;
//   - o HTML de entrada permite zoom, não tem script embutido e declara o idioma.
// São verificações de texto sobre os arquivos, rápidas e sem navegador. O que depende de ver a
// página funcionando (contraste, alvos de toque, teclado) está nos outros testes e na auditoria
// em navegador.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** @param {string} relative */
const read = (relative) => readFileSync(path.join(ROOT, relative), 'utf8')

/** Arquivos de código da aplicação: sem testes e sem o suporte de teste (src/test). */
function appFiles() {
  return readdirSync(path.join(ROOT, 'src'), { recursive: true })
    .map((entry) => String(entry).split(path.sep).join('/'))
    .filter((entry) => /\.(js|jsx)$/.test(entry))
    .filter((entry) => !/\.test\.(js|jsx)$/.test(entry) && !entry.startsWith('test/'))
    .sort()
    .map((entry) => ({ path: `src/${entry}`, source: read(`src/${entry}`) }))
}

const FILES = appFiles()

/** Linha que é só comentário (// , /* , * de JSDoc, {/* ). */
const isCommentLine = (line) => /^\s*(\/\/|\/\*|\*|\{\/\*)/.test(line)

/** Código sem comentários: tira linhas de comentário e o comentário depois do código (" // …"). */
function codeLines(source) {
  return source
    .split('\n')
    .map((text, index) => ({ text: text.replace(/\s\/\/\s.*$/, ''), number: index + 1, raw: text }))
    .filter(({ raw }) => !isCommentLine(raw))
}

/**
 * Onde o padrão aparece no código (fora de comentários), no formato "arquivo:linha".
 * @param {RegExp} pattern
 * @param {string[]} [allowedFiles] arquivos em que o uso é o esperado
 */
function offenders(pattern, allowedFiles = []) {
  const found = []
  for (const file of FILES) {
    if (allowedFiles.includes(file.path)) continue
    for (const { text, number } of codeLines(file.source)) {
      if (pattern.test(text)) found.push(`${file.path}:${number}`)
    }
  }
  return found
}

describe('a própria varredura', () => {
  it('lê os arquivos da aplicação e ignora os de teste', () => {
    const paths = FILES.map((file) => file.path)
    expect(paths.length).toBeGreaterThan(60)
    expect(paths).toContain('src/services/http.js')
    expect(paths).toContain('src/pages/HomePage.jsx')
    expect(paths.some((entry) => entry.endsWith('.test.js') || entry.endsWith('.test.jsx'))).toBe(false)
    expect(paths.some((entry) => entry.startsWith('src/test/'))).toBe(false)
  })

  it('não conta comentários, mas conta código (incluindo comentário no fim da linha)', () => {
    const lines = codeLines(
      ['// localStorage aqui não conta', ' * nem aqui: sessionStorage', 'const a = localStorage // isto é comentário', 'const url = "https://x.y/z"'].join('\n'),
    )
    expect(lines.map((line) => line.text)).toEqual(['const a = localStorage', 'const url = "https://x.y/z"'])
  })
})

describe('nada injeta HTML nem executa texto como código (RNF16)', () => {
  it('sem innerHTML, dangerouslySetInnerHTML, insertAdjacentHTML, document.write ou DOMParser', () => {
    expect(offenders(/dangerouslySetInnerHTML|\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser/)).toEqual([])
  })

  it('sem eval, new Function ou setTimeout/setInterval com texto', () => {
    expect(offenders(/\beval\s*\(|new Function\s*\(|set(Timeout|Interval)\(\s*['"`]/)).toEqual([])
  })

  it('sem endereços javascript: nem manipuladores de evento escritos como texto', () => {
    expect(offenders(/javascript:|\.setAttribute\(\s*['"]on[a-z]+['"]/)).toEqual([])
  })

  it('todo link que abre em outra aba traz rel="noopener noreferrer"', () => {
    for (const file of FILES) {
      for (const match of file.source.matchAll(/<a\b[^>]*target="_blank"[^>]*>/g)) {
        expect(match[0], file.path).toMatch(/rel="noopener noreferrer"/)
      }
    }
  })
})

describe('armazenamento e rede passam por um só módulo', () => {
  it('localStorage, sessionStorage e IndexedDB só em services/storage.js', () => {
    expect(offenders(/\b(localStorage|sessionStorage|indexedDB|openDatabase)\b/, ['src/services/storage.js'])).toEqual([])
  })

  it('o site não usa cookies', () => {
    expect(offenders(/document\.cookie|cookieStore/)).toEqual([])
  })

  it('a rede só é usada em services/http.js (fetch, XHR, beacon, WebSocket)', () => {
    expect(offenders(/\bfetch\s*\(|globalThis\.fetch|window\.fetch|XMLHttpRequest|sendBeacon|new WebSocket|new EventSource/, ['src/services/http.js'])).toEqual([])
  })

  it('as variáveis de ambiente são lidas em um só lugar (src/config.js)', () => {
    expect(offenders(/import\.meta\.env|process\.env/, ['src/config.js'])).toEqual([])
  })

  it('o destino do proxy de desenvolvimento não chega ao código da aplicação', () => {
    expect(offenders(/DEV_API_PROXY_TARGET/)).toEqual([])
  })

  it('não há console.* no código (nada de texto do usuário no console)', () => {
    expect(offenders(/\bconsole\./)).toEqual([])
  })

  it('só os endereços de exemplo e o link do WhatsApp aparecem como http(s)://', () => {
    // O número do WhatsApp vem da configuração (VITE_WHATSAPP_NUMBER); no código, só o endereço do wa.me
    const allowed = new Set(['http://', 'https://', 'https://exemplo.com/noticia', 'https://wa.me/'])
    const found = []
    for (const file of FILES) {
      for (const { text, number } of codeLines(file.source)) {
        for (const match of text.matchAll(/https?:\/\/[^\s'"`)<]*/g)) {
          const url = match[0].replace(/[.,;:]+$/, '')
          if (!allowed.has(url)) found.push(`${file.path}:${number} ${url}`)
        }
      }
    }
    expect(found).toEqual([])
  })
})

describe('texto, nome e campos', () => {
  it('o campo de texto não corta o que foi colado (RF01): nenhum maxLength', () => {
    expect(offenders(/\bmax[Ll]ength\s*=/)).toEqual([])
  })

  it('"Fake Eyes" não aparece em código, página, manifesto, exemplos nem pacote (o nome é Apura)', () => {
    expect(offenders(/Fake[ -]?Eyes/i)).toEqual([])
    for (const file of ['index.html', 'public/site.webmanifest', 'public/robots.txt', '.env.example', 'package.json', 'vite.config.js']) {
      expect(read(file), file).not.toMatch(/Fake[ -]?Eyes/i)
    }
  })

  it('os estilos não carregam nada de fora (sem @import nem url() de outro endereço)', () => {
    const styleDir = path.join(ROOT, 'src', 'styles')
    const sheets = readdirSync(styleDir).filter((entry) => entry.endsWith('.css'))
    expect(sheets.length).toBeGreaterThanOrEqual(6)
    for (const sheet of sheets) {
      const css = readFileSync(path.join(styleDir, sheet), 'utf8')
      expect(css, sheet).not.toMatch(/url\(\s*['"]?(https?:)?\/\//i)
      expect(css, sheet).not.toMatch(/@import\s+(url\(\s*)?['"]?(https?:)?\/\//i)
    }
  })
})

describe('sem segredos (RNF16: tudo o que vai ao navegador é público)', () => {
  const SECRET_PATTERNS = [
    ['chave de API do Google', /AIza[0-9A-Za-z_-]{35}/],
    ['chave no formato sk-', /\bsk-[A-Za-z0-9_-]{20,}/],
    ['Account SID do Twilio', /\bAC[0-9a-f]{32}\b/],
    ['token do GitHub', /\bgh[pousr]_[A-Za-z0-9]{36,}/],
    ['token do Slack', /\bxox[abprs]-[A-Za-z0-9-]{10,}/],
    ['chave privada', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
    ['cabeçalho Authorization com valor', /Bearer\s+[A-Za-z0-9._~+/-]{20,}/],
    ['atribuição de segredo', /\b(api[_-]?key|secret|token|passw(or)?d)\b\s*[:=]\s*['"][^'"\s]{8,}['"]/i],
  ]

  const scanned = () => [
    ...FILES.map((file) => [file.path, file.source]),
    ...['index.html', 'public/site.webmanifest', '.env.example', 'package.json', 'vite.config.js'].map((file) => [file, read(file)]),
  ]

  it.each(SECRET_PATTERNS)('nenhum arquivo contém %s', (_name, pattern) => {
    const found = scanned().filter(([, source]) => pattern.test(source)).map(([file]) => file)
    expect(found).toEqual([])
  })

  it('.env.example só tem variáveis VITE_* e o destino do proxy, e nenhuma com nome de segredo', () => {
    const names = read('.env.example')
      .split('\n')
      .map((line) => line.match(/^([A-Z][A-Z0-9_]*)=/)?.[1])
      .filter(Boolean)
    expect(names.length).toBeGreaterThan(5)
    for (const name of names) {
      expect(name, name).toMatch(/^(VITE_[A-Z0-9_]+|DEV_API_PROXY_TARGET)$/)
      expect(name, name).not.toMatch(/KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIAL/)
    }
  })

  it('.env.example avisa que o que começa com VITE_ vai para o navegador', () => {
    expect(read('.env.example')).toMatch(/VITE_.*navegador/s)
  })

  it('arquivos .env reais não entram no pacote (estão no .gitignore)', () => {
    const ignored = read('.gitignore').split('\n').map((line) => line.trim())
    expect(ignored).toContain('.env')
    expect(ignored).toContain('.env.local')
    expect(ignored).toContain('node_modules/')
    expect(ignored).toContain('dist/')
  })
})

describe('index.html', () => {
  const html = read('index.html')

  it('declara o idioma português do Brasil e um título com o nome do produto', () => {
    expect(html).toMatch(/<html lang="pt-BR">/)
    expect(html).toMatch(/<title>Apura\b[^<]+<\/title>/)
    expect(html).toMatch(/<meta charset="UTF-8"/i)
  })

  it('permite zoom e redimensionamento (WCAG 1.4.4): viewport sem user-scalable=no nem maximum-scale', () => {
    const viewport = html.match(/<meta name="viewport" content="([^"]*)"/)?.[1] ?? ''
    expect(viewport).toContain('width=device-width')
    expect(viewport).toContain('initial-scale=1')
    expect(viewport).not.toMatch(/user-scalable|maximum-scale|minimum-scale/i)
  })

  it('não tem script nem estilo embutido, nem manipuladores de evento (compatível com CSP sem unsafe-inline)', () => {
    const scripts = [...html.matchAll(/<script\b[^>]*>/g)].map((match) => match[0])
    expect(scripts.length).toBeGreaterThan(0)
    for (const tag of scripts) expect(tag).toMatch(/\bsrc="\/src\/main\.jsx"/)
    expect(html).not.toMatch(/<script\b[^>]*>\s*[^<\s]/)
    expect(html).not.toMatch(/<style\b/i)
    expect(html).not.toMatch(/\sstyle="/i)
    expect(html).not.toMatch(/\son[a-z]+="/i)
    expect(html).not.toMatch(/javascript:/i)
  })

  it('não carrega recurso de outro endereço (as fontes vêm do pacote)', () => {
    expect(html).not.toMatch(/\b(src|href)="(https?:)?\/\//i)
    expect(html).not.toMatch(/fonts\.(googleapis|gstatic)\.com/i)
  })

  it('tem aviso para quem está sem JavaScript', () => {
    expect(html).toMatch(/<noscript>[\s\S]*JavaScript[\s\S]*<\/noscript>/)
  })

  it('o manifesto e o robots.txt combinam com o produto: resultados, histórico e conta fora de buscadores', () => {
    const manifest = JSON.parse(read('public/site.webmanifest'))
    expect(manifest.name).toBe('Apura')
    expect(manifest.lang).toBe('pt-BR')
    const robots = read('public/robots.txt')
    for (const route of ['/resultado/', '/historico', '/conta']) expect(robots).toContain(`Disallow: ${route}`)
  })
})
