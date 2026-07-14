from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PerfilUsuario
from ejecutivos.models import Ejecutivo

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    if not created:
        return
    
    #Compara el email de la tabla ejecutivo (data de sap) con el del usuario que inicia sesión, para luego asignarle su codigo_sap
    ejecutivo = Ejecutivo.objects.filter(email=instance.email, activo=True).first()

    codigo_sugerido = None
    if ejecutivo and not PerfilUsuario.objects.filter(codigo_empleado_sap=ejecutivo.codigo_sap).exists():
        codigo_sugerido = ejecutivo.codigo_sap
    
    PerfilUsuario.objects.create(usuario=instance, codigo_empleado_sap=codigo_sugerido)