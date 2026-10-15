/**
 * content.js — ApuraWeb Browser Extension
 *
 * Roda no contexto da página. Escuta a mensagem `extract_content` do popup
 * e responde com o conteúdo principal da página já limpo, pronto para o BERT.
 *
 * Compatível com Chrome (Manifest V3) e Firefox (Manifest V3 / WebExtensions).
 */
(() => {
    // Evita registrar o listener mais de uma vez se o script for injetado duas vezes.
    if (window.__apuraContentScriptLoaded) return;
    window.__apuraContentScriptLoaded = true;

    chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
        if (request.action === 'extract_content') {
            try {
                const articleData = extractMainContent();
                sendResponse({ success: true, data: articleData });
            } catch (err) {
                sendResponse({ success: false, error: err.message });
            }
        }
        // Retorna true para manter o canal de resposta aberto (assíncrono no Firefox)
        return true;
    });

    function extractMainContent() {
        // --- Título ---
        // Prioridade: og:title > <h1> > <title>
        const ogTitle = document.querySelector('meta[property="og:title"]')?.getAttribute('content');
        const h1Title = document.querySelector('article h1, main h1, h1')?.innerText;
        const title = (ogTitle || h1Title || document.title || '').trim();

        // --- Subtítulo (linha-fina) ---
        // O modelo V4 foi treinado com "título [SEP] subtítulo [SEP] texto".
        // Prioridade: linha-fina visível > og:description > meta description.
        const subtitleEl = document.querySelector(
            '.content-head__subtitle, .subtitle, .sub-title, .linha-fina, .article-subtitle, ' +
            '.c-headline__subtitle, .lead, article h2, main h2'
        );
        const ogDesc = document.querySelector('meta[property="og:description"]')?.getAttribute('content');
        const metaDesc = document.querySelector('meta[name="description"]')?.getAttribute('content');
        let subtitle = (subtitleEl?.innerText || ogDesc || metaDesc || '').trim();
        if (subtitle === title) subtitle = '';
        subtitle = subtitle.slice(0, 2000); // max_length do serializer

        // --- Clona o body para não modificar a página ao vivo ---
        const clone = document.body.cloneNode(true);

        // --- Remove elementos irrelevantes ---
        const elementsToRemove = [
            'header', 'footer', 'nav', 'aside',
            '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
            '[role="complementary"]', '[role="search"]',
            '.sidebar', '#sidebar', '.side-bar', '#side-bar',
            '.menu', '#menu', '.nav', '#nav',
            '.ads', '.ad', '.advertisement', '.adsbygoogle',
            '.social', '.social-share', '.share', '.sharing',
            '.comments', '#comments', '.comment-section',
            '.related', '.related-posts', '.recommended',
            '.subscription', '.newsletter', '.popup',
            '.cookie', '.cookie-banner', '.gdpr',
            'script', 'style', 'iframe', 'noscript', 'figure > figcaption',
        ];

        elementsToRemove.forEach(selector => {
            try {
                clone.querySelectorAll(selector).forEach(el => el.remove());
            } catch (_) { /* seletor inválido — ignora */ }
        });

        // --- Encontra o contêiner principal do artigo ---
        // Prioridade: og:url aponta para a página; usamos sinais semânticos.
        const candidates = [
            'article[class*="article"]', 'article[class*="post"]',
            '[role="main"] article', '[role="main"]',
            'main article', 'main',
            '.article-body', '.article-content', '.article-text',
            '.post-body', '.post-content', '.post-text',
            '.entry-content', '.entry-body',
            '.story-body', '.story-content',
            '.content-body', '.page-content',
            '#article-body', '#content',
            'article',
        ];

        let container = null;
        for (const selector of candidates) {
            const el = clone.querySelector(selector);
            if (el && el.innerText && el.innerText.trim().length > 200) {
                container = el;
                break;
            }
        }
        if (!container) container = clone;

        // --- Coleta parágrafos significativos ---
        // Mínimo 40 chars para eliminar avisos de cookies, legendas e fragmentos.
        const paragraphs = Array.from(container.querySelectorAll('p, blockquote, li'))
            .map(p => p.innerText?.trim() || '')
            .filter(text => text.length > 40);

        // Fallback: texto bruto do contêiner se não encontrar parágrafos suficientes
        let mainContent = paragraphs.join('\n\n');
        if (mainContent.length < 100) {
            mainContent = (container.innerText || '').trim();
        }

        // Limita para não ultrapassar o MAX_CHARS do servidor (20.000 somando título + subtítulo + texto)
        const maxContent = 19000 - title.length - subtitle.length;
        if (mainContent.length > maxContent) {
            mainContent = mainContent.slice(0, maxContent);
        }

        return {
            title,
            subtitle,
            content: mainContent,
            url: window.location.href,
        };
    }
})();