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


def _search_fact_check_fallback(query: str) -> list[dict[str, Any]]:
    """
    Fallback: Busca em checagens públicas brasileiras e internacionais de fact-checking.
    Utiliza endpoint lite para evitar desafios de tela cheia/bloqueio.
    """
    search_term = f"{query} checagem fato fake"
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.post(url, data={"q": search_term}, headers=headers, timeout=6)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[dict[str, Any]] = []

        rows = soup.select("table tr")
        for row in rows:
            link_el = row.select_one("a.result-link")
            if not link_el:
                continue

            title = link_el.get_text(strip=True)
            raw_link = link_el.get("href") or ""
            snippet_tr = row.find_next_sibling("tr")
            snippet = (
                snippet_tr.select_one("td.result-snippet").get_text(strip=True)
                if snippet_tr and snippet_tr.select_one("td.result-snippet")
                else ""
            )

            # Identifica se é veículo de checagem conhecido
            publisher = "Agência de Notícias / Checagem"
            for domain, name in KNOWN_PUBLISHERS.items():
                if domain in raw_link.lower() or domain in title.lower():
                    publisher = name
                    break

            # Determina a relação a partir do título e snippet
            combined_text = f"{title} {snippet}".lower()
            if any(w in combined_text for w in ("é falso", "é fake", "não é verdade", "boato", "engana", "distorce", "desment", "es falso", "desmente", "falso")):
                relation = "conflicting"
                reason = "A apuração de fact-checking indica que a alegação é falsa ou enganosa."
            elif any(w in combined_text for w in ("é fato", "é verdade", "verdadeiro", "confirma", "es verdad")):
                relation = "compatible"
                reason = "A apuração indica que os fatos relatados são verídicos."
            else:
                relation = "contextual"
                reason = "Publicação de checagem com contextualização sobre o tema."

            results.append({
                "id": f"src-{len(results) + 1}",
                "relation": relation,
                "publisher": publisher,
                "title": title,
                "excerpt": snippet,
                "published_at": None,
                "url": raw_link,
                "relation_reason": reason,
            })

            if len(results) >= 4:
                break

        return results
    except Exception:
        logger.exception("Falha no fallback de checagem de fatos")
        return []


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
