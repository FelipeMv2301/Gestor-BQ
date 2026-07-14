from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.http import HttpResponseForbidden
from dotenv import load_dotenv
import os

#Llamar función que trae las variables de entorno desde .env
load_dotenv()

#Variables traídas
DOMINIO_PERMITIDO = os.getenv('DOMINIO_PERMITIDO')


class BioquimicaSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        email = sociallogin.account.extra_data.get("email", "")
        if not email.endswith(DOMINIO_PERMITIDO):
            raise ImmediateHttpResponse(
                HttpResponseForbidden("Acceso disponible solo a cuentas @bioquimica.cl")
            )