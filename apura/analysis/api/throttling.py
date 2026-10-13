"""
Throttling personalizado da API.

Requisições originadas da extensão de navegador (header X-Client-Source: browser-extension)
são isentas de limite de uso — a extensão não tem quota por cliente (RF-extensao-01).
Todas as demais requisições anônimas continuam sujeitas ao limite definido em API_ANON_RATE.
"""

from rest_framework.throttling import AnonRateThrottle


class ExtensionOrAnonThrottle(AnonRateThrottle):
    """
    Herda AnonRateThrottle mas libera requisições que trazem o marcador da extensão.
    Qualquer requisição com o header  X-Client-Source: browser-extension  é isenta.
    """

    def allow_request(self, request, view):
        if request.headers.get("X-Client-Source") == "browser-extension":
            return True  # sem quota para a extensão
        return super().allow_request(request, view)
