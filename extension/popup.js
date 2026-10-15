/**
 * popup.js — ApuraWeb Browser Extension
 *
 * Conecta o popup ao content script e ao servidor Django.
 * Endpoint correto: POST /api/v1/analyses/
 * Requisições identificadas com X-Client-Source: browser-extension → sem quota.
 */

const SERVER_URL = 'http://127.0.0.1:8000/api/v1/analyses/';

// ── Estado da aplicação ──────────────────────────────────────────────────────
let currentResult = null;

// ── Referências DOM ───────────────────────────────────────────────────────────
const views = {
    initial: document.getElementById('view-initial'),
    loading: document.getElementById('view-loading'),
    error:   document.getElementById('view-error'),
    result:  document.getElementById('view-result'),
};

const analyzeBtn      = document.getElementById('analyze-btn');
const retryBtn        = document.getElementById('retry-btn');
const newAnalysisBtn  = document.getElementById('new-analysis-btn');
const openModalBtn    = document.getElementById('open-modal-btn');
const closeModalBtn   = document.getElementById('close-modal');
const modalBackdrop   = document.getElementById('modal-backdrop');
const modalEl         = document.getElementById('modal');
const errorMessageEl  = document.getElementById('error-message');

// ── Navegação entre views ─────────────────────────────────────────────────────
function showView(name) {
    Object.entries(views).forEach(([key, el]) => {
        el.classList.toggle('hidden', key !== name);
    });
}

// ── Análise principal ─────────────────────────────────────────────────────────
async function runAnalysis() {
    showView('loading');

    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.id) throw new Error('Nenhuma aba ativa encontrada.');

        // Injeta o content script (seguro reinjetar — tem guard interno)
        try {
            await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                files: ['content.js'],
            });
        } catch (_) { /* já injetado ou sem permissão — tenta enviar assim mesmo */ }

        // Extrai conteúdo da página
        const response = await new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tab.id, { action: 'extract_content' }, res => {
                if (chrome.runtime.lastError) {
                    reject(new Error('Não foi possível ler o conteúdo desta página. Tente recarregá-la.'));
                } else {
                    resolve(res);
                }
            });
        });

        if (!response || !response.success) {
            throw new Error(response?.error || 'Falha ao extrair o conteúdo da página.');
        }

        const { title, subtitle, content, url } = response.data;

        if (!content || content.trim().length < 50) {
            throw new Error('O conteúdo desta página é muito curto ou não pôde ser lido. Tente em um artigo completo.');
        }

        // Envia para o servidor Django
        const apiResponse = await fetch(SERVER_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Client-Source': 'browser-extension',
            },
            body: JSON.stringify({
                input_type: 'text',
                title,
                subtitle,
                text: content,
                url,
            }),
        });

        const data = await apiResponse.json();

        if (!apiResponse.ok) {
            const errMsg = data?.error?.message || `Erro ${apiResponse.status} do servidor.`;
            const errAction = data?.error?.action || '';
            throw new Error(errAction ? `${errMsg}\n${errAction}` : errMsg);
        }

        if (data.status !== 'ok' || !data.result) {
            throw new Error('O servidor retornou uma resposta inesperada.');
        }

        currentResult = data.result;
        renderResult(currentResult);

    } catch (err) {
        showError(err.message || 'Erro desconhecido.');
    }
}

// ── Renderização do resultado simplificado ────────────────────────────────────
function renderResult(result) {
    const banner      = document.getElementById('verdict-banner');
    const iconEl      = document.getElementById('verdict-icon');
    const labelEl     = document.getElementById('verdict-label');
    const scoreEl     = document.getElementById('verdict-score');
    const summaryEl   = document.getElementById('verdict-summary');
    const riskSection = document.getElementById('risk-bar-section');
    const riskFill    = document.getElementById('risk-bar-fill');
    const riskMarker  = document.getElementById('risk-bar-marker');

    const discoursePill = document.getElementById('discourse-pill');
    const scopePill     = document.getElementById('scope-pill');
    const alertBox      = document.getElementById('verdict-alert');
    const alertTitle    = document.getElementById('alert-title');
    const alertMsg      = document.getElementById('alert-message');

    const statModelLabel = document.getElementById('stat-model-label');
    const statFakeProb   = document.getElementById('stat-fake-prob');
    const statConfidence = document.getElementById('stat-confidence');

    // Remove classes de tom anteriores
    banner.className = 'verdict-banner';

    const VERDICT_CONFIG = {
        SAFE:         { cls: 'verdict--safe',        icon: '✅', label: result.label },
        SUSPICIOUS:   { cls: 'verdict--suspicious',  icon: '⚠️', label: result.label },
        DANGER:       { cls: 'verdict--danger',       icon: '🚨', label: result.label },
        INCONCLUSIVE: { cls: 'verdict--inconclusive', icon: '🔍', label: result.label },
    };

    const cfg = VERDICT_CONFIG[result.verdict_code] || VERDICT_CONFIG.INCONCLUSIVE;
    banner.classList.add(cfg.cls);
    iconEl.textContent  = cfg.icon;
    labelEl.textContent = cfg.label;
    scoreEl.textContent = result.risk_index != null ? `Índice de risco: ${result.score}` : result.score;

    // Badges de discurso e escopo de treino
    if (result.discourse_label) {
        discoursePill.textContent = result.discourse_label;
        discoursePill.className = 'badge-pill';
        if (result.discourse_type === 'satira') {
            discoursePill.classList.add('badge-pill--satire');
        } else if (result.discourse_type === 'teoria_conspiratoria' || result.discourse_type === 'conspiracy_or_theoretical') {
            discoursePill.classList.add('badge-pill--conspiracy');
        }
        discoursePill.classList.remove('hidden');
    } else {
        discoursePill.classList.add('hidden');
    }

    if (result.is_out_of_domain) {
        scopePill.classList.remove('hidden');
    } else {
        scopePill.classList.add('hidden');
    }

    // Alerta específico (sátira / modelo treinado em imprensa tradicional / incerteza)
    if (result.alert && result.alert.message) {
        alertBox.className = `verdict-alert verdict-alert--${result.alert.type || 'warning'}`;
        alertTitle.textContent = result.alert.title || 'Aviso';
        alertMsg.textContent = result.alert.message;
        alertBox.classList.remove('hidden');
    } else {
        alertBox.classList.add('hidden');
    }

    summaryEl.textContent = result.summary || '';

    // Barra de risco (só exibe se tiver índice numérico)
    if (result.risk_index != null) {
        riskSection.classList.remove('hidden');
        const pct = Math.min(100, Math.max(0, result.risk_index));
        riskFill.style.width = `${pct}%`;
        riskMarker.style.left = `${pct}%`;
        // Cor da barra segundo faixa
        if (pct <= 25) {
            riskFill.className = 'risk-bar-fill risk-fill--low';
        } else if (pct <= 60) {
            riskFill.className = 'risk-bar-fill risk-fill--mid';
        } else {
            riskFill.className = 'risk-bar-fill risk-fill--high';
        }
    } else {
        riskSection.classList.add('hidden');
    }

    // Estatísticas rápidas
    statModelLabel.textContent = result.model_label || '—';
    statFakeProb.textContent   = result.fake_probability != null ? `${result.fake_probability}%` : '—';
    statConfidence.textContent = result.confidence != null ? `${result.confidence}%` : '—';

    showView('result');
}

// ── Renderização do modal de detalhes ─────────────────────────────────────────
function renderModal(result) {
    // Veredito
    const verdictEl = document.getElementById('modal-verdict');
    verdictEl.innerHTML = `
        <span class="modal-verdict-badge modal-verdict-badge--${result.verdict_code?.toLowerCase() || 'inconclusive'}">
            ${result.label}
        </span>
        <span class="modal-verdict-score">${result.score}</span>
    `;

    // Comparação Semântica e Consenso
    const semanticSection = document.getElementById('modal-semantic-section');
    const semanticBadge   = document.getElementById('modal-semantic-badge');
    const semanticText    = document.getElementById('modal-semantic-text');
    const sem = result.semantic_comparison || {};
    if (sem.consensus_summary) {
        semanticSection.classList.remove('hidden');
        if (sem.consensus_status === 'diverge_consenso') {
            semanticBadge.className = 'consensus-badge consensus-badge--divergent';
            semanticBadge.textContent = 'Diverge do Consenso Factual';
        } else if (sem.consensus_status === 'conforme_consenso') {
            semanticBadge.className = 'consensus-badge consensus-badge--compatible';
            semanticBadge.textContent = 'Compatível com o Consenso';
        } else {
            semanticBadge.className = 'consensus-badge consensus-badge--neutral';
            semanticBadge.textContent = 'Debate Teórico / Sem Consenso Definido';
        }
        semanticText.textContent = sem.consensus_summary;
    } else {
        semanticSection.classList.add('hidden');
    }

    // Marcadores Léxicos de Especulação (Hedging)
    const hedgingSection = document.getElementById('modal-hedging-section');
    const hedgingChips   = document.getElementById('modal-hedging-chips');
    const lex = result.lexical_analysis || {};
    const hedgingTerms = lex.hedging_terms || [];
    if (hedgingTerms.length > 0) {
        hedgingSection.classList.remove('hidden');
        hedgingChips.innerHTML = hedgingTerms.map(term => `<span class="chip">“${escHtml(term)}”</span>`).join('');
    } else {
        hedgingSection.classList.add('hidden');
    }

    // Explicação
    fillList('modal-explanation', result.explanation || [], item => `<li>${escHtml(item)}</li>`);

    // Recomendações
    fillList('modal-recommendations', result.recommendations || [], item => `<li>💡 ${escHtml(item)}</li>`);

    // Evidências / fontes
    const evidenceEl = document.getElementById('modal-evidence');
    const evidenceSection = document.getElementById('modal-evidence-section');
    const sources = result.evidence?.sources || [];
    if (sources.length > 0) {
        evidenceSection.classList.remove('hidden');
        evidenceEl.innerHTML = sources.map(s => `
            <div class="evidence-item">
                <div class="evidence-publisher">${escHtml(s.publisher || 'Fonte desconhecida')}</div>
                <div class="evidence-title">${escHtml(s.title || '')}</div>
                ${s.url ? `<a href="${escHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="evidence-link">Ver fonte ↗</a>` : ''}
            </div>
        `).join('');
    } else {
        evidenceSection.classList.add('hidden');
    }

    // Limitações
    fillList('modal-limitations', result.limitations || [], item => `<li>${escHtml(item)}</li>`);

    // Dados técnicos
    const techEl = document.getElementById('modal-technical');
    const fd = result.full_details || {};
    const model = fd.model || {};
    const versions = fd.versions || {};
    techEl.innerHTML = `
        <table class="tech-table">
            <tr><td>ID da análise</td><td class="tech-val mono">${escHtml(fd.id || '—')}</td></tr>
            <tr><td>Data/hora</td><td class="tech-val">${fd.created_at ? new Date(fd.created_at).toLocaleString('pt-BR') : '—'}</td></tr>
            <tr><td>Tempo de análise</td><td class="tech-val">${fd.duration_ms ? `${Math.round(fd.duration_ms)} ms` : '—'}</td></tr>
            <tr><td>Tipo de discurso</td><td class="tech-val">${escHtml(result.discourse_label || '—')}</td></tr>
            <tr><td>Escopo de treino</td><td class="tech-val mono">${escHtml(result.training_scope || '—')}</td></tr>
            <tr><td>Fora de domínio</td><td class="tech-val">${result.is_out_of_domain ? 'Sim' : 'Não'}</td></tr>
            <tr><td>Trechos analisados</td><td class="tech-val">${model.chunks_analyzed ?? '—'} / ${model.chunks_total ?? '—'}</td></tr>
            <tr><td>Tokens analisados</td><td class="tech-val">${model.tokens_analyzed ?? '—'} / ${model.tokens_total ?? '—'}</td></tr>
            <tr><td>Dispositivo</td><td class="tech-val">${escHtml(model.device || '—')}</td></tr>
            <tr><td>Versão do modelo</td><td class="tech-val mono">${escHtml(versions.model || '—')}</td></tr>
            <tr><td>Versão das regras</td><td class="tech-val mono">${escHtml(versions.rules || '—')}</td></tr>
            <tr><td>Versão do schema</td><td class="tech-val mono">${escHtml(versions.schema || '—')}</td></tr>
            <tr><td>Versão do código</td><td class="tech-val mono">${escHtml(versions.code || '—')}</td></tr>
        </table>
    `;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fillList(elId, items, rowFn) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = items.length > 0
        ? items.map(rowFn).join('')
        : '<li class="empty-note">Nenhuma informação disponível.</li>';
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function showError(msg) {
    errorMessageEl.textContent = msg;
    showView('error');
}

function openModal() {
    if (!currentResult) return;
    renderModal(currentResult);
    modalEl.classList.remove('hidden');
    document.getElementById('modal-title').focus();
}

function closeModal() {
    modalEl.classList.add('hidden');
}

// ── Event listeners ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    showView('initial');
});

analyzeBtn.addEventListener('click', runAnalysis);
retryBtn.addEventListener('click', () => { showView('initial'); });
newAnalysisBtn.addEventListener('click', () => { currentResult = null; showView('initial'); });
openModalBtn.addEventListener('click', openModal);
closeModalBtn.addEventListener('click', closeModal);
modalBackdrop.addEventListener('click', closeModal);

// Fechar modal com Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !modalEl.classList.contains('hidden')) {
        closeModal();
    }
});