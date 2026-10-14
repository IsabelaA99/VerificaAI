"""
Módulo de raspagem de notícias a partir de URL (RF02, RF03, RNF09).

Utiliza o trafilatura para contornar popups, consentimentos de cookies, modais
e boilerplates de páginas de notícias, com fallback para BeautifulSoup e
proteção estrita contra SSRF (Server-Side Request Forgery).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests
import urllib3
from bs4 import BeautifulSoup
import trafilatura

from .preprocessing import InputValidationError, normalize_text
from .timing import Deadline

logger = logging.getLogger(__name__)
MAX_REDIRECTS = 5

# Cabeçalhos realistas de navegador desktop moderno para evitar bloqueios antirrobô
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class ScrapedArticle:
    url: str
    domain: str
    title: str
    subtitle: str
    body: str
    author: Optional[str] = None
    published_at: Optional[str] = None


def _public_destination(url: str) -> tuple[str, str, int]:
    """
    Valida todos os endereços DNS e devolve um IP público para a conexão.
    O cliente HTTP deve usar esse IP, sem fazer uma segunda resolução DNS.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise InputValidationError(
            "invalid_url", "O endereço informado não é válido.",
            "Verifique o formato da URL e tente novamente.", field="url",
        ) from exc

    if parsed.scheme not in ("http", "https"):
        raise InputValidationError(
            "invalid_url_scheme",
            "Apenas links com endereço 'http://' ou 'https://' são permitidos.",
            "Verifique o endereço colado e tente novamente.",
            field="url",
        )

    if not hostname or not port or parsed.username is not None or parsed.password is not None:
        raise InputValidationError(
            "invalid_url",
            "O endereço informado não contém um nome de domínio válido.",
            "Verifique o formato da URL e tente novamente.",
            field="url",
        )

    # Bloqueio de localhost e nomes locais
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        raise InputValidationError(
            "forbidden_url",
            "Não é permitido analisar endereços de redes locais ou internas.",
            "Insira o endereço de um site de notícias público na internet.",
            field="url",
        )

    # Verifica todas as respostas A/AAAA; nunca usa uma resposta não validada.
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        if not resolved:
            raise socket.gaierror("sem endereços DNS")
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise InputValidationError(
                    "forbidden_url",
                    "O endereço aponta para um servidor interno ou restrito.",
                    "Insira o endereço de um site de notícias público na internet.",
                    field="url",
                )
    except socket.gaierror as exc:
        raise InputValidationError(
            "dns_resolution_failed",
            "Não foi possível localizar o site informado na internet.",
            "Verifique se o endereço foi digitado corretamente.",
            field="url",
        ) from exc

    return hostname, resolved[0][4][0], port


def validate_url_safety(url: str) -> str:
    """Valida uma URL contra SSRF e retorna seu hostname público."""
    hostname, _, _ = _public_destination(url)
    return hostname


def _get_public_url(url: str, timeout: int, deadline: Deadline | None = None) -> requests.Response:
    """Busca cada salto por IP validado, mantendo Host, SNI e validação TLS."""
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        if deadline:
            deadline.check()
        prepared = requests.Request("GET", current_url, headers=BROWSER_HEADERS).prepare()
        current_url = prepared.url
        hostname, ip, port = _public_destination(current_url)
        headers = dict(prepared.headers)
        default_port = 443 if current_url.startswith("https://") else 80
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        headers["Host"] = host_header if port == default_port else f"{host_header}:{port}"

        pool_type = (
            urllib3.HTTPSConnectionPool if current_url.startswith("https://")
            else urllib3.HTTPConnectionPool
        )
        pool_kwargs = {}
        if pool_type is urllib3.HTTPSConnectionPool:
            pool_kwargs = {
                "server_hostname": hostname,
                "assert_hostname": hostname,
                "cert_reqs": "CERT_REQUIRED",
                "ca_certs": requests.certs.where(),
            }
        with pool_type(ip, port, **pool_kwargs) as pool:
            raw = pool.urlopen(
                "GET", prepared.path_url, headers=headers,
                timeout=deadline.timeout(timeout) if deadline else timeout,
                retries=False, redirect=False, decode_content=True,
            )
            response = requests.Response()
            response.status_code = raw.status
            response.headers = requests.structures.CaseInsensitiveDict(raw.headers)
            response._content = raw.data
            response.url = current_url
            response.encoding = requests.utils.get_encoding_from_headers(response.headers)

        location = response.headers.get("Location")
        if response.status_code in (301, 302, 303, 307, 308) and location:
            if redirect_count == MAX_REDIRECTS:
                raise InputValidationError(
                    "too_many_redirects", "O endereço redirecionou muitas vezes.",
                    "Insira o link direto da matéria jornalística.", field="url",
                )
            current_url = urllib.parse.urljoin(current_url, location)
            continue
        return response

    raise AssertionError("limite de redirecionamentos não aplicado")


def scrape_url(url: str, timeout: int = 12, *, deadline: Deadline | None = None) -> ScrapedArticle:
    """
    Raspa uma notícia a partir da URL, contornando popups de cookies/anúncios.
    """
    # 1. Download do HTML com proteção e cabeçalhos de navegador
    try:
        response = _get_public_url(url, timeout, deadline=deadline)
    except (requests.exceptions.Timeout, urllib3.exceptions.TimeoutError) as exc:
        raise InputValidationError(
            "url_timeout",
            "O site de notícias demorou muito para responder.",
            "Tente novamente ou cole o texto da notícia diretamente no formulário.",
            field="url",
        ) from exc
    except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError) as exc:
        raise InputValidationError(
            "network_error",
            "Não foi possível conectar ao site da notícia.",
            "Verifique se o site está acessível ou cole o texto diretamente.",
            field="url",
        ) from exc

    domain = urllib.parse.urlsplit(response.url).hostname or ""

    if response.status_code == 403 or response.status_code == 401:
        raise InputValidationError(
            "paywall_or_forbidden",
            "O site bloqueou o acesso automático (paywall ou proteção antirrobô).",
            "Copie o texto da notícia e cole diretamente na aba 'Colar texto'.",
            field="url",
        )

    if response.status_code >= 400:
        raise InputValidationError(
            "http_error",
            f"O site retornou erro {response.status_code}.",
            "Verifique se a matéria ainda existe ou cole o texto diretamente.",
            field="url",
        )

    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise InputValidationError(
            "non_text_content",
            "O endereço informado não parece ser uma página de texto ou notícia.",
            "Insira o link direto da matéria jornalística.",
            field="url",
        )

    html_content = response.text

    # 2. Extração com Trafilatura (elimina popups, avisos de cookies, menus e footers)
    doc = trafilatura.bare_extraction(
        html_content,
        url=response.url or url,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
        with_metadata=True,
    )

    title = ""
    subtitle = ""
    body = ""
    author = None
    published_at = None

    if doc:
        title = getattr(doc, "title", None) or (doc.get("title") if isinstance(doc, dict) else "") or ""
        body = getattr(doc, "text", None) or (doc.get("text") if isinstance(doc, dict) else "") or ""
        author = getattr(doc, "author", None) or (doc.get("author") if isinstance(doc, dict) else None)
        published_at = getattr(doc, "date", None) or (doc.get("date") if isinstance(doc, dict) else None)

    # 3. Fallback com BeautifulSoup para metatags OpenGraph / Schema.org
    soup = BeautifulSoup(html_content, "html.parser")

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = str(og_title["content"]).strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()

    # Tenta obter subtítulo / linha-fina
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content"):
        desc = str(og_desc["content"]).strip()
        if desc and desc != title:
            subtitle = desc

    # Se o corpo extraído pelo Trafilatura for muito pequeno, busca parágrafos do <article>
    if len(body) < 100:
        article_el = soup.find("article") or soup.find("main") or soup.find("div", class_=re.compile(r"content|materia|noticia|post", re.I))
        if article_el:
            paragraphs = [p.get_text(strip=True) for p in article_el.find_all("p") if len(p.get_text(strip=True)) > 20]
            if paragraphs:
                body = "\n\n".join(paragraphs)

    title = normalize_text(title)
    subtitle = normalize_text(subtitle)
    body = normalize_text(body)

    if not body and not title:
        raise InputValidationError(
            "empty_scraped_text",
            "Não foi possível extrair o texto da matéria neste endereço.",
            "Cole o conteúdo da notícia diretamente no campo de texto.",
            field="url",
        )

    # Se o corpo for curto mas o título existir, concatena o subtítulo se houver
    if len(body) < 50:
        if subtitle and len(body) + len(subtitle) >= 50:
            body = f"{subtitle}\n\n{body}".strip()
            subtitle = ""

    return ScrapedArticle(
        url=response.url or url,
        domain=domain.lower(),
        title=title,
        subtitle=subtitle,
        body=body,
        author=author,
        published_at=published_at,
    )
