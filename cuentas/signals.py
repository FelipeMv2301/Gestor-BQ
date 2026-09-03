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

    #El escalar es 1:1 (unique=True en DB, legacy): solo se rellena si ningún otro perfil lo tiene ya.
    #La M2M sí permite que varios perfiles compartan el mismo código (decisión de Felipe 2026-09-02:
    #visibilidad compartida de los pedidos de ese código entre todos sus dueños) — se vincula siempre
    #que haya match por email, esté o no ocupado el escalar.
    escalar_ocupado = ejecutivo and PerfilUsuario.objects.filter(codigo_empleado_sap=ejecutivo.codigo_sap).exists()
    codigo_sugerido = ejecutivo.codigo_sap if ejecutivo and not escalar_ocupado else None

    perfil = PerfilUsuario.objects.create(usuario=instance, codigo_empleado_sap=codigo_sugerido)
    if ejecutivo is not None:
        perfil.ejecutivos.add(ejecutivo)   # M2M es la fuente de verdad; el escalar queda como fallback