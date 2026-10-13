"""
Serviço de checagem externa de fatos (RF07, RF08).

Integra a API Google Fact Check Tools (ClaimReview) com fallback inteligente
para checagens de agências brasileiras (Aos Fatos, Agência Lupa, G1 Fato ou Fake,
Boatos.org, E-farsas, UOL Confere).
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_FACTCHECK_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

KNOWN_PUBLISHERS = {
    "g1.globo.com": "G1 Fato ou Fake",
    "aosfatos.org": "Aos Fatos",
    "lupa.uol.com.br": "Agência Lupa",
    "boatos.org": "Boatos.org",
    "e-farsas.com": "E-farsas",
    "noticias.uol.com.br/confere": "UOL Confere",
    "confere.uol.com.br": "UOL Confere",
    "estadao.com.br/estadao-verifica": "Estadão Verifica",
    "chequeado.com": "Chequeado",
    "factual.afp.com": "AFP Checamos",
    "observador.pt": "Observador Fact Check",
    "projetocomprova.com.br": "Projeto Comprova",
}


def _extract_query_keywords(claim_text: str, max_words: int = 8) -> str:
    """Extrai as palavras mais significativas da alegação para busca."""
    clean = re.sub(r"[^\w\s]", " ", claim_text, flags=re.UNICODE)
    words = clean.split()
    stopwords = {
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
        "em", "no", "na", "nos", "nas", "para", "por", "com", "que", "se", "nao", "não",
        "e", "ou", "mas", "como", "ao", "aos", "pelo", "pela", "pelos", "pelas", "este",
        "esta", "esse", "essa", "isso", "isto", "urgente", "compartilhe", "veja", "foto",
        "libera", "liberam", "documento", "documentos", "evidencia", "evidencias",
        "evidência", "evidências", "fortalece", "fortalecem", "teoria", "teorias",
        "revela", "revelam", "mostra", "mostram", "segundo", "afirma", "diz",
    }
    keywords = [w for w in words if len(w) > 2 and w.lower() not in stopwords]
    if not keywords:
        keywords = [w for w in words if len(w) > 2]
    return " ".join(keywords[:max_words])


def _search_google_fact_check(query: str, api_key: str) -> list[dict[str, Any]]:
    """Consulta a API oficial do Google Fact Check Tools."""
    params = {
        "query": query,
        "languageCode": "pt-BR",
        "pageSize": 5,
        "key": api_key,
    }
    try:
        resp = requests.get(GOOGLE_FACTCHECK_URL, params=params, timeout=6)
        if resp.status_code != 200:
            logger.warning("Google Fact Check API retornou status %s", resp.status_code)
            return []
        data = resp.json()
        claims = data.get("claims") or []
        results: list[dict[str, Any]] = []

        for i, claim_item in enumerate(claims):
            claim_text = claim_item.get("text", "")
            for review in claim_item.get("claimReview", []):
                publisher_info = review.get("publisher", {})
                publisher_name = publisher_info.get("name") or "Agência de Checagem"
                title = review.get("title") or claim_text
                rating = (review.get("textualRating") or "").strip()
                review_url = review.get("url") or ""
                review_date = review.get("reviewDate") or claim_item.get("claimDate")

                rating_lower = rating.lower()
                if any(w in rating_lower for w in ("falso", "fake", "enganoso", "distorcido", "mentira", "inverdade", "incorreto")):
                    relation = "conflicting"
                    reason = f"Classificado como '{rating}' pela checagem oficial."
                elif any(w in rating_lower for w in ("verdadeiro", "fato", "correto", "real")):
                    relation = "compatible"
                    reason = f"Classificado como '{rating}' pela checagem oficial."
                else:
                    relation = "contextual"
                    reason = f"Traz contexto ou avaliação parcial ('{rating}')."

                results.append({
                    "id": f"gfc-{i + 1}",
                    "relation": relation,
                    "publisher": publisher_name,
                    "title": title,
                    "excerpt": f"Alegação: {claim_text}. Veredito da checagem: {rating}." if rating else claim_text,
                    "published_at": review_date,
                    "url": review_url,
                    "relation_reason": reason,
                })

        return results
    except Exception:
        logger.exception("Falha ao consultar Google Fact Check API")
        return []


_STOPWORDS_QUERY = {
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "para", "por",
    "com", "que", "se", "nao", "não", "uma", "um", "este", "esta", "esse", "essa",
    "isso", "isto", "como", "pelo", "pela", "pelos", "pelas", "ontem", "hoje", "amanha", "amanhã", "sobre",
    "segundo", "afirma", "diz", "anuncia", "anunciou", "revela", "mostra"
}


def _check_overlap(query: str, text: str) -> int:
    """Calcula quantos radicais significativos da busca aparecem no texto."""
    q_stems = {w[:4].lower() for w in query.lower().split() if len(w) >= 3 and w.lower() not in _STOPWORDS_QUERY}
    t_stems = {w[:4].lower() for w in text.lower().split() if len(w) >= 3 and w.lower() not in _STOPWORDS_QUERY}
    return len(q_stems.intersection(t_stems))


def _clean_html_snippet(text: str) -> str:
    """Remove tags HTML e normaliza espaços."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _search_comprova(query: str, max_results: int = 2) -> list[dict[str, Any]]:
    """Consulta o Projeto Comprova (consórcio de 28 redações jornalísticas no Brasil)."""
    url = f"https://projetocomprova.com.br/?s={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items: list[dict[str, Any]] = []
        for art in soup.select("article"):
            link_el = art.select_one("h2 a, .post-title a")
            desc_el = art.select_one("p, .entry-content, .post-excerpt")
            if not link_el or not link_el.get("href"):
                continue
            title = _clean_html_snippet(link_el.get_text(strip=True))
            href = link_el.get("href") or ""
            snippet = _clean_html_snippet(desc_el.get_text(strip=True) if desc_el else "")

            overlap = _check_overlap(query, f"{title} {snippet}")
            if overlap == 0:
                continue

            combined = f"{title} {snippet}".lower()
            is_debunk = any(w in combined for w in ("falso", "falsa", "fake", "enganoso", "enganosa", "distorce", "desmente", "desment", "golpe", "sem provas", "boato"))
            is_valid = any(w in combined for w in ("verdadeiro", "verdadeira", "é fato", "é verdade", "comprovado", "real"))

            if is_debunk and overlap >= 2:
                relation = "conflicting"
                reason = "Publicação do Projeto Comprova aponta alegação falsa ou desmentida."
            elif is_valid and overlap >= 2:
                relation = "compatible"
                reason = "Publicação do Projeto Comprova confirma a veracidade factual."
            else:
                relation = "contextual"
                reason = "Investigação jornalística do Projeto Comprova trazendo apuração de contexto."

            items.append({
                "id": f"comprova-{len(items) + 1}",
                "relation": relation,
                "publisher": "Projeto Comprova",
                "title": title,
                "excerpt": snippet[:280],
                "published_at": None,
                "url": href,
                "relation_reason": reason,
            })
            if len(items) >= max_results:
                break
        return items
    except Exception:
        logger.warning("Falha ao buscar checagem no Projeto Comprova")
        return []


def _search_boatos(query: str, max_results: int = 2) -> list[dict[str, Any]]:
    """Consulta o Boatos.org (agência independente brasileira de desmentidos)."""
    url = f"https://www.boatos.org/?s={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items: list[dict[str, Any]] = []
        for art in soup.select("article"):
            link_el = art.select_one("h2 a")
            desc_el = art.select_one(".entry-summary p, .entry-content p, p")
            if not link_el or not link_el.get("href"):
                continue
            title = _clean_html_snippet(link_el.get_text(strip=True))
            href = link_el.get("href") or ""
            snippet = _clean_html_snippet(desc_el.get_text(strip=True) if desc_el else "")

            overlap = _check_overlap(query, f"{title} {snippet}")
            if overlap == 0:
                continue

            combined = f"{title} {snippet}".lower()
            is_debunk = any(w in combined for w in ("#boato", "boato", "falso", "falsa", "fake", "mentira", "golpe", "desmente", "desmentido", "distorcido"))
            is_valid = any(w in combined for w in ("fato", "verdade", "real"))

            if is_debunk and overlap >= 2:
                relation = "conflicting"
                reason = "Checagem do Boatos.org aponta que a narrativa é boato ou desinformação."
            elif is_valid and overlap >= 2:
                relation = "compatible"
                reason = "Checagem confirma a ocorrência do fato."
            else:
                relation = "contextual"
                reason = "Artigo de checagem do Boatos.org contextualizando o boato."

            items.append({
                "id": f"boatos-{len(items) + 1}",
                "relation": relation,
                "publisher": "Boatos.org",
                "title": title,
                "excerpt": snippet[:280],
                "published_at": None,
                "url": href,
                "relation_reason": reason,
            })
            if len(items) >= max_results:
                break
        return items
    except Exception:
        logger.warning("Falha ao buscar checagem no Boatos.org")
        return []


def _search_wikipedia(query: str, max_results: int = 2) -> list[dict[str, Any]]:
    """Consulta a Wikipédia em português para consenso histórico, científico e enciclopédico."""
    url = "https://pt.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
        "srlimit": max_results,
    }
    headers = {"User-Agent": "VerificAI/1.0 (contato: marlon.marques.mmd@gmail.com)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code != 200:
            return []
        items_data = resp.json().get("query", {}).get("search", [])
        results: list[dict[str, Any]] = []
        query_words = [w for w in query.lower().split() if len(w) > 3]

        for i, it in enumerate(items_data):
            title = it.get("title", "")
            snippet = _clean_html_snippet(it.get("snippet", ""))
            combined = f"{title} {snippet}".lower()

            # Evita artigos genéricos desconectados da alegação
            if query_words:
                overlap = sum(1 for w in query_words if w in combined)
                if overlap < 2 and len(query_words) > 1:
                    continue

            if any(w in combined for w in ("teoria da conspiração", "teorias da conspiração", "pseudociência", "fraude", "boato", "desmentido")):
                relation = "conflicting"
                reason = "Registro enciclopédico oficial documenta o tema como teoria da conspiração ou pseudociência."
            else:
                relation = "contextual"
                reason = "Contexto enciclopédico e histórico de referência (Wikipédia)."

            clean_title = title.replace(" ", "_")
            results.append({
                "id": f"wiki-{len(results) + 1}",
                "relation": relation,
                "publisher": "Wikipédia (Consenso Enciclopédico)",
                "title": title,
                "excerpt": snippet[:280],
                "published_at": None,
                "url": f"https://pt.wikipedia.org/wiki/{urllib.parse.quote(clean_title)}",
                "relation_reason": reason,
            })
        return results
    except Exception:
        logger.warning("Falha ao buscar contexto na Wikipédia")
        return []


def _search_fact_check_fallback(query: str) -> list[dict[str, Any]]:
    """
    Fallback integrado de checagem pública:
    1. Projeto Comprova (consórcio das maiores redações brasileiras)
    2. Boatos.org (desmentidos independentes)
    3. Wikipédia (registro histórico e científico de teorias e consensos)
    """
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # Busca em checagens jornalísticas especializadas
    for source in _search_comprova(query) + _search_boatos(query):
        url = source.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            results.append(source)

    # Se não encontrou apuração em agências, ou se restou espaço, consulta o consenso enciclopédico
    if len(results) < 3:
        for wiki_item in _search_wikipedia(query):
            url = wiki_item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(wiki_item)
            if len(results) >= 4:
                break

    # Reindexa os IDs sequencialmente
    for idx, item in enumerate(results, 1):
        item["id"] = f"src-{idx}"

    return results[:4]


def search_fact_checks(claim_or_title: str) -> dict[str, Any]:
    """
    Busca checagens de fatos para a notícia ou alegação.
    Retorna estrutura padronizada para o serializer e pipeline:
    {
        "status": "found" | "none",
        "enabled": True,
        "sources": [...],
        "conflict_score": 1.0 | 0.0 | None
    }
    """
    if not claim_or_title or len(claim_or_title.strip()) < 5:
        return {"status": "none", "enabled": True, "sources": [], "conflict_score": None}

    query = _extract_query_keywords(claim_or_title)
    api_key = settings.FAKE_EYES.get("GOOGLE_FACT_CHECK_API_KEY", "")

    sources: list[dict[str, Any]] = []

    # 1. Tenta a API oficial do Google Fact Check se a chave estiver configurada
    if api_key:
        sources = _search_google_fact_check(query, api_key)

    # 2. Se não houver chave ou a API retornar vazio, utiliza o fallback
    if not sources:
        sources = _search_fact_check_fallback(query)

    # Avaliação do conflito de evidências (RF08)
    has_conflicting = any(s.get("relation") == "conflicting" for s in sources)
    has_compatible = any(s.get("relation") == "compatible" for s in sources)

    conflict_score: float | None = None
    if has_conflicting:
        conflict_score = 1.0  # Conflitante com a alegação analisada
    elif has_compatible:
        conflict_score = 0.0  # Compatível com a alegação analisada

    return {
        "status": "found" if sources else "none",
        "enabled": True,
        "sources": sources,
        "conflict_score": conflict_score,
    }
