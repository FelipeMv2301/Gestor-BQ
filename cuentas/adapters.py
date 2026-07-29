from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.http import HttpResponseForbidden
from dotenv import load_dotenv
import logging
import os

#Llamar función que trae las variables de entorno desde .env
load_dotenv()

#Variables traídas
DOMINIO_PERMITIDO = os.getenv('DOMINIO_PERMITIDO')

logger = logging.getLogger("allauth")


class BioquimicaSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        email = sociallogin.account.extra_data.get("email", "")
        if not email.endswith(DOMINIO_PERMITIDO):
            raise ImmediateHttpResponse(
                HttpResponseForbidden("Acceso disponible solo a cuentas @bioquimica.cl")
            )

    #TEMPORAL: diagnóstico del login Google en gestor-test (2026-07-29) — allauth atrapa la
    #excepción del intercambio OAuth2 y muestra su propia pantalla de error sin loguear nada.
    #Sacar cuando se resuelva.
    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        logger.error(
            "Fallo autenticación social: error=%s exception=%r extra_context=%s",
            error, exception, extra_context, exc_info=exception,
        )
        super().on_authentication_error(request, provider, error=error, exception=exception, extra_context=extra_context)