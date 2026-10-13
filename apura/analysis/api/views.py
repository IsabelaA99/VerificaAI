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

logger = logging.getLogger(__name__)


class AnalysisCreateView(APIView):
    """POST /api/v1/analyses/ — executa a análise de forma síncrona (≤ 30 s, RNF01)."""

    def post(self, request):
        serializer = AnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            if data["input_type"] == Analysis.InputType.URL:
                analysis = run_url_analysis(
                    url=data["url"],
                    user=request.user,
                    visitor_id=request.headers.get("X-Visitor-Id", ""),
                )
            else:
                analysis = run_text_analysis(
                    text=data["text"],
                    title=data.get("title", ""),
                    subtitle=data.get("subtitle", ""),
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
