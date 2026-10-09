(() => {
    // Escuta comandos enviados pelo popup
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.action === 'extract_content') {
            try {
                const articleData = extractMainContent();
                sendResponse({ success: true, data: articleData });
            } catch (err) {
                sendResponse({ success: false, error: err.message });
            }
        }
        return true; // Mantém o canal de resposta aberto para retorno assíncrono
    });

    function extractMainContent() {
        // 1. Título do artigo
        let title = document.querySelector('h1')?.innerText || document.title || '';

        // 2. Clona o documento para manipular e limpar sem afetar a página ativa
        const clone = document.body.cloneNode(true);

        // 3. Remove elementos indesejados (Anúncios, Menus, Footers, Sidebars)
        const selectorsToRemove = [
            'header', 'footer', 'nav', 'aside',
            '.sidebar', '#sidebar', '.menu', '#menu',
            '.ads', '.ad', '.advertisement', '.social-share',
            'script', 'style', 'iframe', 'noscript'
        ];

        selectorsToRemove.forEach(selector => {
            clone.querySelectorAll(selector).forEach(el => el.remove());
        });

        // 4. Seleção estratégica do contêiner do artigo
        let container = clone.querySelector('article, [role="main"], main, .post-content, .article-content, .content');
        if (!container) {
            container = clone;
        }

        // 5. Coleta parágrafos significativos para alimentar o BERT
        const paragraphs = Array.from(container.querySelectorAll('p'))
            .map(p => p.innerText.trim())
            .filter(text => text.length > 30); // Descarta avisos de cookies ou frases curtas

        const mainContent = paragraphs.join('\n\n');

        return {
            title: title.trim(),
            content: mainContent,
            url: window.location.href
        };
    }
})();