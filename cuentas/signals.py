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

    #Solo autoasigna si ese código SAP no lo tiene ya otro perfil (ni en el escalar ni en la M2M) — un código = un dueño
    codigo_ocupado = ejecutivo and (
        PerfilUsuario.objects.filter(codigo_empleado_sap=ejecutivo.codigo_sap).exists()
        or PerfilUsuario.objects.filter(ejecutivos=ejecutivo).exists()
    )
    codigo_sugerido = ejecutivo.codigo_sap if ejecutivo and not codigo_ocupado else None

    perfil = PerfilUsuario.objects.create(usuario=instance, codigo_empleado_sap=codigo_sugerido)
    if codigo_sugerido is not None:
        perfil.ejecutivos.add(ejecutivo)   # M2M es la fuente de verdad; el escalar queda como fallback