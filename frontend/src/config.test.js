import { describe, expect, it } from 'vitest'
import { createConfig } from './config.js'

// A configuração vem de variáveis VITE_* e vai para o pacote do navegador (RNF16): nada de segredo.

describe('createConfig', () => {
  it('sem variáveis, os padrões são os do projeto', () => {
    expect(createConfig({})).toEqual({
      apiBaseUrl: '/api',
      requestTimeoutMs: 30_000, // RNF01
      urlInput: true,
      accountsMode: 'demo',
      feedbackMode: 'demo',
      backend: { urlAnalysis: true, sources: true },
    })
  })

  it('a configuração não pode ser alterada depois de criada', () => {
    const config = createConfig({})
    expect(Object.isFrozen(config)).toBe(true)
    expect(() => {
      'use strict'
      config.apiBaseUrl = 'https://outro.exemplo'
    }).toThrow(TypeError)
  })

  describe('endereço da API', () => {
    it('usa o informado e tira as barras do fim (para não gerar "//v1")', () => {
      expect(createConfig({ VITE_API_BASE_URL: 'https://api.exemplo.org/' }).apiBaseUrl).toBe('https://api.exemplo.org')
      expect(createConfig({ VITE_API_BASE_URL: '/api///' }).apiBaseUrl).toBe('/api')
    })

    it('vazio volta ao padrão /api (mesma origem, ADR-006)', () => {
      expect(createConfig({ VITE_API_BASE_URL: '' }).apiBaseUrl).toBe('/api')
    })
  })

  describe('prazo de espera (RNF01)', () => {
    it('aceita um número positivo', () => {
      expect(createConfig({ VITE_REQUEST_TIMEOUT_MS: '45000' }).requestTimeoutMs).toBe(45_000)
    })

    it.each(['0', '-5', 'abc', '', 'NaN', 'Infinity'])('valor inválido (%j) cai nos 30 s do requisito', (value) => {
      expect(createConfig({ VITE_REQUEST_TIMEOUT_MS: value }).requestTimeoutMs).toBe(30_000)
    })
  })

  describe('entrada por link', () => {
    it('vem ligada por padrão; só "false" desliga', () => {
      expect(createConfig({}).urlInput).toBe(true)
      expect(createConfig({ VITE_FEATURE_URL_INPUT: '' }).urlInput).toBe(true)
      expect(createConfig({ VITE_FEATURE_URL_INPUT: 'false' }).urlInput).toBe(false)
      expect(createConfig({ VITE_FEATURE_URL_INPUT: 'true' }).urlInput).toBe(true)
    })
  })

  describe('contas e avaliação', () => {
    it('"off" desliga; qualquer outro valor fica em demonstração (nunca liga um modo real que não existe)', () => {
      expect(createConfig({ VITE_ACCOUNTS_MODE: 'off' }).accountsMode).toBe('off')
      expect(createConfig({ VITE_ACCOUNTS_MODE: 'demo' }).accountsMode).toBe('demo')
      expect(createConfig({ VITE_ACCOUNTS_MODE: 'real' }).accountsMode).toBe('demo')
      expect(createConfig({ VITE_FEEDBACK_MODE: 'off' }).feedbackMode).toBe('off')
      expect(createConfig({ VITE_FEEDBACK_MODE: 'real' }).feedbackMode).toBe('demo')
    })

    it('são independentes entre si', () => {
      const config = createConfig({ VITE_ACCOUNTS_MODE: 'off', VITE_FEEDBACK_MODE: 'demo' })
      expect(config.accountsMode).toBe('off')
      expect(config.feedbackMode).toBe('demo')
    })
  })

  describe('o que o back end já faz (só muda textos explicativos, RF30)', () => {
    it('acompanham a API atual por padrão; "false" serve a um back end anterior', () => {
      expect(createConfig({}).backend).toEqual({ urlAnalysis: true, sources: true })
      expect(createConfig({ VITE_BACKEND_URL_ANALYSIS: 'false' }).backend).toEqual({ urlAnalysis: false, sources: true })
      expect(createConfig({ VITE_BACKEND_SOURCES: 'false' }).backend).toEqual({ urlAnalysis: true, sources: false })
      expect(createConfig({ VITE_BACKEND_SOURCES: 'sim' }).backend.sources).toBe(false)
    })
  })

  it('só lê variáveis VITE_* (as demais nem chegam ao pacote do navegador)', () => {
    const config = createConfig({ SECRET: 'x', DEV_API_PROXY_TARGET: 'http://localhost:8000' })
    expect(JSON.stringify(config)).not.toContain('localhost')
    expect(JSON.stringify(config)).not.toContain('SECRET')
  })
})
