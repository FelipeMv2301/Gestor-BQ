from pedidos.permisos import obtener_rol, codigos_sap_usuario
from cuentas.models import PerfilUsuario
from .models import Cotizacion

def queryset_cotizaciones_visible(usuario):
      rol = obtener_rol(usuario)
      perfil = getattr(usuario, "perfil", None)

      # ADMIN total, o supervisor comercial (flag) → ven todas
      if rol == PerfilUsuario.Rol.ADMIN or getattr(perfil, "ve_todas_cotizaciones", False):
          return Cotizacion.objects.all()

      if rol == PerfilUsuario.Rol.EJECUTIVO:
          codigos = codigos_sap_usuario(usuario)
          if not codigos:
              return Cotizacion.objects.none()
          return Cotizacion.objects.filter(ejecutivo__codigo_sap__in=codigos)

      # LOGISTICA y cualquier otro rol: no ven cotizaciones
      return Cotizacion.objects.none()