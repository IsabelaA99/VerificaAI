const SERVER_URL = 'http://127.0.0.1:8000/api/analyze/'; // Endpoint Django

document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyze-btn');
    const loadingEl = document.getElementById('loading');
    const errorBoxEl = document.getElementById('error-box');
    const errorMsgEl = document.getElementById('error-message');
    const resultBoxEl = document.getElementById('result-box');

    const verdictBadge = document.getElementById('verdict-badge');
    const verdictTitle = document.getElementById('verdict-title');
    const verdictScore = document.getElementById('verdict-score');
    const verdictSummary = document.getElementById('verdict-summary');

    const openModalBtn = document.getElementById('open-modal-btn');
    const closeModalBtn = document.getElementById('close-modal');
    const modalEl = document.getElementById('modal');
    const modalJsonEl = document.getElementById('modal-json');

    let currentAnalysisDetails = null;

    analyzeBtn.addEventListener('click', async () => {
        resetUI();
        loadingEl.classList.remove('hidden');

        try {
            // 1. Obtém a aba atual do navegador
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            if (!tab) throw new Error('Nenhuma aba ativa encontrada.');

            // 2. Injeta o content.js dinamicamente se necessário e envia mensagem de extração
            await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ['content.js']
            }).catch(() => { }); // Ignora se já estiver injetado

            chrome.tabs.sendMessage(tab.id, { action: 'extract_content' }, async (response) => {
                if (chrome.runtime.lastError || !response || !response.success) {
                    showError('Não foi possível ler o conteúdo desta página.');
                    return;
                }

                const scrapedData = response.data;

                // 3. Envia os dados extraídos para o servidor Django
                try {
                    const apiResponse = await fetch(SERVER_URL, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Client-Source': 'browser-extension' // Identificador da extensão
                        },
                        body: JSON.stringify({
                            title: scrapedData.title,
                            content: scrapedData.content,
                            url: scrapedData.url,
                            is_extension: true
                        })
                    });

                    const data = await apiResponse.json();

                    if (!apiResponse.ok || data.status === 'error') {
                        throw new Error(data.message || 'Erro ao obter resposta do servidor.');
                    }

                    // 4. Renderiza resultado simplificado
                    renderResult(data.result);

                } catch (fetchErr) {
                    showError(`Falha de conexão com o servidor: ${fetchErr.message}`);
                }
            });

        } catch (err) {
            showError(err.message);
        }
    });

    function renderResult(result) {
        loadingEl.classList.add('hidden');
        resultBoxEl.classList.remove('hidden');

        verdictTitle.innerText = result.label;
        verdictScore.innerText = result.score;
        verdictSummary.innerText = result.summary;

        currentAnalysisDetails = result.full_details;

        // Atualiza cor da badge
        if (result.verdict_code === 'SAFE') {
            verdictBadge.style.backgroundColor = '#22c55e';
        } else if (result.verdict_code === 'SUSPICIOUS') {
            verdictBadge.style.backgroundColor = '#eab308';
        } else {
            verdictBadge.style.backgroundColor = '#ef4444';
        }
    }

    function showError(msg) {
        loadingEl.classList.add('hidden');
        errorBoxEl.classList.remove('hidden');
        errorMsgEl.innerText = msg;
    }

    function resetUI() {
        loadingEl.classList.add('hidden');
        errorBoxEl.classList.add('hidden');
        resultBoxEl.classList.add('hidden');
    }

    // Controle do Modal
    openModalBtn.addEventListener('click', () => {
        modalJsonEl.innerText = JSON.stringify(currentAnalysisDetails, null, 2);
        modalEl.classList.remove('hidden');
    });

    closeModalBtn.addEventListener('click', () => {
        modalEl.classList.add('hidden');
    });
});