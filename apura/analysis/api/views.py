"""Views da API v1."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Analysis
from ..services import classifier as classifier_service
from ..services import risk
from ..services.pipeline import SCHEMA_VERSION, code_version, run_text_analysis, run_url_analysis
from ..services.preprocessing import InputValidationError
from .errors import error_response
from .serializers import AnalysisRequestSerializer, AnalysisResultSerializer
from .throttling import ExtensionOrAnonThrottle

logger = logging.getLogger(__name__)


def _is_extension_request(request) -> bool:
    """Detecta se a requisição vem da extensão de navegador."""
    return request.headers.get("X-Client-Source") == "browser-extension"


def _extension_response(analysis: Analysis) -> dict:
    """
    Formata a resposta de forma amigável para a extensão.

    Campos simplificados para exibição direta e campo `full_details`
    com o resultado completo para o modal de detalhes.
    """
    full = AnalysisResultSerializer(analysis).data

    status_obj = full.get("status", {})
    status_code = status_obj.get("code", "")
    status_label = status_obj.get("label", "Análise inconclusiva")

    risk_index = full.get("risk_index")
    model_info = full.get("model", {})
    explanation = full.get("explanation", [])

    # Mapeia status_code → verdict_code para coloração na extensão
    verdict_map = {
        Analysis.Status.LOW: "SAFE",
        Analysis.Status.ATTENTION: "SUSPICIOUS",
        Analysis.Status.HIGH: "DANGER",
        Analysis.Status.INCONCLUSIVE: "INCONCLUSIVE",
    }
    verdict_code = verdict_map.get(status_code, "INCONCLUSIVE")

    # Rótulo do modelo (verdadeira / falsa)
    model_label_display = "Verdadeira" if model_info.get("label") == "verdadeira" else "Falsa"
    fake_prob = model_info.get("fake_probability", 0)
    confidence = model_info.get("confidence", 0)

    if risk_index is not None:
        score_text = f"{round(risk_index)}/100"
    else:
        score_text = "Inconclusivo"

    summary = explanation[0] if explanation else "Sem informações adicionais."

    return {
        "status": "ok",
        "result": {
            "verdict_code": verdict_code,
            "label": status_label,
            "score": score_text,
            "risk_index": risk_index,
            "summary": summary,
            "model_label": model_label_display,
            "fake_probability": round(fake_prob * 100, 1),
            "confidence": round(confidence * 100, 1),
            "explanation": explanation,
            "recommendations": full.get("recommendations", []),
            "evidence": full.get("evidence", {}),
            "abstention": full.get("abstention", []),
            "limitations": full.get("limitations", []),
            "claim": full.get("claim", {}),
            "duration_ms": full.get("duration_ms"),
            "full_details": full,
        },
    }


class AnalysisCreateView(APIView):
    """POST /api/v1/analyses/ — executa a análise de forma síncrona (≤ 30 s, RNF01)."""

    throttle_classes = [ExtensionOrAnonThrottle]

    def post(self, request):
        # Requisições da extensão podem enviar {title, content, url, is_extension}
        # Normalizamos para o formato interno antes de validar.
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)

        if _is_extension_request(request):
            # A extensão envia o conteúdo já raspado; mapeamos para o campo `text`.
            if "content" in data and "text" not in data:
                data["text"] = data.pop("content")
            # Garante input_type = text (a extensão já fez o scraping)
            data.setdefault("input_type", Analysis.InputType.TEXT)
            # Remove campos que não pertencem ao serializer
            data.pop("is_extension", None)
            data.pop("url", None)

        serializer = AnalysisRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        try:
            if validated["input_type"] == Analysis.InputType.URL:
                analysis = run_url_analysis(
                    url=validated["url"],
                    user=request.user,
                    visitor_id=request.headers.get("X-Visitor-Id", ""),
                )
            else:
                analysis = run_text_analysis(
                    text=validated["text"],
                    title=validated.get("title", ""),
                    subtitle=validated.get("subtitle", ""),
                    user=request.user,
                    visitor_id=request.headers.get("X-Visitor-Id", ""),
                )
        except InputValidationError as exc:
            return error_response(exc.code, exc.message, exc.action, status.HTTP_400_BAD_REQUEST,
                                  field=exc.field, details=exc.extra or None)
        except Exception:  # noqa: BLE001 — falha técnica controlada, sem vazar texto
            logger.exception("Falha ao executar a análise")
            return error_response(
                "analysis_unavailable",
                "Não foi possível concluir a análise agora.",
                "Tente novamente em alguns instantes.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Resposta diferenciada para extensão
        if _is_extension_request(request):
            return Response(_extension_response(analysis), status=status.HTTP_201_CREATED)

        return Response(AnalysisResultSerializer(analysis).data, status=status.HTTP_201_CREATED)


class AnalysisDetailView(APIView):
    """GET /api/v1/analyses/<id>/ — recupera o resultado e as versões usadas."""

    def get(self, request, analysis_id):
        analysis = Analysis.objects.filter(pk=analysis_id).first()
        if analysis is None:
            return error_response("analysis_not_found", "Análise não encontrada.",
                                  "Verifique o identificador informado.", status.HTTP_404_NOT_FOUND)
        if analysis.user_id and analysis.user_id != getattr(request.user, "id", None):
            return error_response("analysis_not_found", "Análise não encontrada.",
                                  "Verifique o identificador informado.", status.HTTP_404_NOT_FOUND)
        return Response(AnalysisResultSerializer(analysis).data)


class HealthView(APIView):
    """GET /api/v1/health/ — disponibilidade e versões dos componentes."""

    throttle_classes: list = []

    def get(self, request):
        rules = risk.load_rules()
        payload = {
            "status": "ok",
            "api_version": "v1",
            "schema_version": SCHEMA_VERSION,
            "code_version": code_version(),
            "rules_version": rules.version,
            "calibrator_version": rules.calibrator.get("version"),
            "model_loaded": classifier_service.is_loaded(),
        }
        if request.query_params.get("load") == "1" or classifier_service.is_loaded():
            try:
                payload["model"] = classifier_service.get_classifier().info()
                payload["model_loaded"] = True
            except Exception:  # noqa: BLE001
                logger.exception("Falha ao carregar o modelo")
                payload["status"] = "degraded"
        return Response(payload, status=200 if payload["status"] == "ok" else 503)
