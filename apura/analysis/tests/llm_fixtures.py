"""Respostas fictícias do contrato externo de síntese, sem chamadas de rede."""

import json


def valid_llm_payload():
    return {
        "summary": "Resumo de teste",
        "key_points": ["Ponto de teste"],
        "verdict_tendency": "inconclusiva",
        "discourse_type": "factual",
        "discourse_label": "Relato Factual",
        "semantic_comparison": {
            "claim_analyzed": "Alegação de teste",
            "consensus_status": "nao_verificado",
            "consensus_summary": "Sem conclusão factual",
        },
        "lexical_analysis": {
            "hedging_detected": False,
            "hedging_terms": [],
            "rhetorical_devices": [],
            "formality_gap_warning": "",
        },
        "uncertainty_warning": "",
    }


def response_envelope(payload, *, gemini=False):
    content = json.dumps(payload)
    if gemini:
        return {"candidates": [{"content": {"parts": [{"text": content}]}}]}
    return {"choices": [{"message": {"content": content}}]}
