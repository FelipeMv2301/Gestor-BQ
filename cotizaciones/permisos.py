from pedidos.permisos import obtener_rol
from cuentas.models import PerfilUsuario
from .models import Cotizacion

def queryset_cotizaciones_visible(usuario):
      rol = obtener_rol(usuario)
      perfil = getattr(usuario, "perfil", None)

      # ADMIN total, o supervisor comercial (flag) → ven todas
      if rol == PerfilUsuario.Rol.ADMIN or getattr(perfil, "ve_todas_cotizaciones", False):
          return Cotizacion.objects.all()

      if rol == PerfilUsuario.Rol.EJECUTIVO:
          codigo = getattr(perfil, "codigo_empleado_sap", None)
          if codigo is None:
              return Cotizacion.objects.none()
          return Cotizacion.objects.filter(ejecutivo__codigo_sap=codigo)

      # LOGISTICA y cualquier otro rol: no ven cotizaciones
      return Cotizacion.objects.none()