"""Serializers da API v1."""

from __future__ import annotations

from rest_framework import serializers

from ..models import Analysis
from ..services import risk

RECOMMENDATIONS = [
    "Procure a fonte original da informação antes de compartilhar.",
    "Compare com veículos de imprensa e agências de checagem reconhecidas.",
    "Verifique a data de publicação e se o conteúdo não está fora de contexto.",
    "Evite compartilhar enquanto houver dúvida sobre a veracidade.",
]


class AnalysisRequestSerializer(serializers.Serializer):
    """Entrada: apenas a opção selecionada (texto OU URL) é considerada (RF24)."""

    input_type = serializers.ChoiceField(choices=Analysis.InputType.choices, default=Analysis.InputType.TEXT)
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False, max_length=50000)
    title = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    subtitle = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    url = serializers.CharField(required=False, allow_blank=True, max_length=2048)

    def validate(self, attrs):
        if attrs["input_type"] == Analysis.InputType.TEXT:
            if not (attrs.get("text") or "").strip():
                raise serializers.ValidationError({"text": "Informe o texto da notícia."})
            attrs.pop("url", None)
        else:
            if not (attrs.get("url") or "").strip():
                raise serializers.ValidationError({"url": "Informe o endereço da notícia."})
            for key in ("text", "title", "subtitle"):
                attrs.pop(key, None)
        return attrs


def _explanation(obj: Analysis) -> list[str]:
    """Explicação em linguagem simples (RF17), separando modelo, indicadores e fontes."""
    tech = obj.technical or {}
    ling = tech.get("linguistic_indicators", {})
    llm_info = tech.get("llm_analysis", {})
    items: list[str] = []

    if obj.status == Analysis.Status.INCONCLUSIVE:
        items.extend(risk.ABSTENTION_MESSAGES.get(r, r) for r in obj.abstention_reasons)

    # Alerta de incerteza da análise de especialista
    if llm_info.get("uncertainty_warning"):
        items.append(llm_info["uncertainty_warning"])

    # Síntese e motivos gerados pela LLM / motor analítico ("por isso e por isso")
    if llm_info.get("summary"):
        items.append(llm_info["summary"])
    if llm_info.get("key_points"):
        items.extend(llm_info["key_points"])

    sem_comp = llm_info.get("semantic_comparison") or {}
    if sem_comp.get("consensus_summary") and not any(sem_comp["consensus_summary"][:30] in it for it in items):
        if sem_comp.get("consensus_status") == "diverge_consenso":
            items.append(f"Confronto com o consenso: {sem_comp['consensus_summary']}")
        elif sem_comp.get("consensus_status") == "conforme_consenso":
            items.append(f"Consenso factual: {sem_comp['consensus_summary']}")

    if not llm_info:
        if obj.model_label == "falsa":
            items.append("O padrão de escrita do texto se parece com o de notícias falsas vistas no treinamento do modelo.")
        else:
            items.append("O padrão de escrita do texto se parece com o de notícias verdadeiras vistas no treinamento do modelo.")
    elif llm_info.get("discourse_type") in ("conspiracy_or_theoretical", "opinion"):
        items.append(
            "Nota metodológica: O modelo BERTimbau foi treinado exclusivamente com matérias da imprensa tradicional (reconhecimento de estilo formal). Ele não foi treinado para validar teorias históricas ou conspiratórias. A avaliação factual deste conteúdo baseia-se prioritariamente nas checagens de fatos (Fact Check) e no consenso historiográfico."
        )

    terms = ling.get("sensational_terms") or []
    if terms and not any(terms[0] in it for it in items):
        items.append("Foram encontradas expressões apelativas: " + ", ".join(f"“{t}”" for t in terms) + ".")
    if ling.get("components", {}).get("caps", 0) >= 0.5:
        items.append("O texto usa muitas palavras em caixa alta.")
    if ling.get("components", {}).get("punctuation", 0) >= 0.5:
        items.append("O texto usa pontuação excessiva, como várias exclamações.")
    return items


class AnalysisResultSerializer(serializers.ModelSerializer):
    api_version = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    claim = serializers.SerializerMethodField()
    explanation = serializers.SerializerMethodField()
    abstention = serializers.SerializerMethodField()
    model = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField()
    limitations = serializers.SerializerMethodField()
    recommendations = serializers.SerializerMethodField()
    versions = serializers.SerializerMethodField()
    risk = serializers.SerializerMethodField()
    expert = serializers.SerializerMethodField()

    class Meta:
        model = Analysis
        fields = [
            "id", "api_version", "created_at", "input_type", "status", "risk_index", "claim",
            "explanation", "abstention", "evidence", "indicators", "model", "risk",
            "limitations", "recommendations", "versions", "duration_ms", "expert",
        ]

    def get_api_version(self, obj):
        return "v1"

    def get_status(self, obj):
        return {"code": obj.status, "label": obj.get_status_display()}

    def get_claim(self, obj):
        return {"summary": obj.claim_summary, "confirmed_by_user": False}

    def get_explanation(self, obj):
        return _explanation(obj)

    def get_abstention(self, obj):
        return [{"code": r, "message": risk.ABSTENTION_MESSAGES.get(r, r)} for r in obj.abstention_reasons]

    def get_model(self, obj):
        cls = (obj.technical or {}).get("classification", {})
        llm_info = (obj.technical or {}).get("llm_analysis", {})
        discourse_type = llm_info.get("discourse_type", "factual")
        is_out_of_domain = cls.get(
            "is_out_of_domain",
            discourse_type in ("conspiracy_or_theoretical", "teoria_conspiratoria", "satira", "opinion")
        )
        training_scope = cls.get("training_scope", "in_domain_general")
        return {
            "label": obj.model_label,
            "fake_probability": obj.model_fake_probability,
            "confidence": obj.model_confidence,
            "calibrated": (obj.technical or {}).get("calibrator", {}).get("calibrated", False),
            "discourse_type": discourse_type,
            "discourse_label": llm_info.get("discourse_label", "Relato Factual"),
            "is_out_of_domain": is_out_of_domain,
            "training_scope": training_scope,
            "semantic_comparison": llm_info.get("semantic_comparison") or {},
            "lexical_analysis": llm_info.get("lexical_analysis") or {},
            "uncertainty_warning": llm_info.get("uncertainty_warning", ""),
            "chunks_analyzed": cls.get("chunks_analyzed"),
            "chunks_total": cls.get("chunks_total"),
            "chunk_fake_probabilities": cls.get("chunk_fake_probabilities"),
            "chunk_disagreement": cls.get("chunk_disagreement"),
            "tokens_analyzed": cls.get("tokens_analyzed"),
            "tokens_total": cls.get("tokens_total"),
            "fully_analyzed": cls.get("fully_analyzed"),
            "aggregation": cls.get("aggregation"),
            "latency_ms": cls.get("latency_ms"),
            "device": cls.get("device"),
        }

    def get_expert(self, obj):
        llm_info = (obj.technical or {}).get("llm_analysis", {})
        if not llm_info:
            return None
        return {
            "discourse_type": llm_info.get("discourse_type", "factual"),
            "discourse_label": llm_info.get("discourse_label", "Relato Factual"),
            "semantic_comparison": llm_info.get("semantic_comparison") or {},
            "lexical_analysis": llm_info.get("lexical_analysis") or {},
            "uncertainty_warning": llm_info.get("uncertainty_warning", ""),
            "provider": llm_info.get("provider", ""),
        }

    def get_indicators(self, obj):
        return (obj.technical or {}).get("linguistic_indicators", {})

    def get_evidence(self, obj):
        return (obj.technical or {}).get("evidence", {"enabled": True, "sources": []})

    def get_risk(self, obj):
        return (obj.technical or {}).get("risk", {})

    def get_limitations(self, obj):
        return (obj.technical or {}).get("limitations", [])

    def get_recommendations(self, obj):
        return RECOMMENDATIONS

    def get_versions(self, obj):
        return {
            "model": obj.model_version,
            "model_sha256": obj.model_sha256,
            "rules": obj.rules_version,
            "calibrator": obj.calibrator_version,
            "schema": obj.schema_version,
            "code": obj.code_version,
        }
