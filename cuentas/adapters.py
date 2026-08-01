from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
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

        #Reconciliación por email: si este login Google todavía no está enlazado a un
        #SocialAccount pero ya existe un User con el mismo correo, conectarlos aquí para
        #evitar el formulario de signup (que pediría username). Complementa a
        #SOCIALACCOUNT_EMAIL_AUTHENTICATION como cinturón y tirantes.
        if sociallogin.is_existing:
            return
        existing_user = get_user_model().objects.filter(email__iexact=email).first()
        if existing_user:
            sociallogin.connect(request, existing_user)

    #TEMPORAL: diagnóstico del login Google en gestor-test (2026-07-29) — allauth atrapa la
    #excepción del intercambio OAuth2 y muestra su propia pantalla de error sin loguear nada.
    #Sacar cuando se resuelva.
    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        logger.error(
            "Fallo autenticación social: error=%s exception=%r extra_context=%s",
            error, exception, extra_context, exc_info=exception,
        )
        super().on_authentication_error(request, provider, error=error, exception=exception, extra_context=extra_context)