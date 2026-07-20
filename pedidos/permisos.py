from cuentas.models import PerfilUsuario
from .models import Pedido

"""
Manejar los permisos de cada usuario y por funcionalidades.
1. Muestra los datos dependiendo de que tipo de usuario eres.
2. Permite la edición / cancelación de pedidos dependiendo del estado del pedido y de tu rol
"""


#Llama con getattr el rol del usuario, sin romper nada más
def obtener_rol(usuario):
    perfil = getattr(usuario, "perfil", None)
    rol = getattr  (perfil, "rol", None)
    return rol

#Compara el código de empleado que tiene la cuenta de usuario con el que está asociado el pedido como tal
def responsable_del_pedido(usuario, pedido):
    perfil = getattr(usuario, "perfil", None)
    if perfil is None or pedido.ejecutivo_id is None:
        return False
    return perfil.codigo_empleado_sap == pedido.ejecutivo.codigo_sap

#Permiso necesario para cambiar el estado_comercial 
def puede_aprobar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return True
    if rol == PerfilUsuario.Rol.EJECUTIVO and responsable_del_pedido(usuario, pedido):
        return True
    return False

#Permiso específico para pasar un pedido a pedidosRechazados
def puede_rechazar(usuario, pedido):
    return obtener_rol(usuario) == PerfilUsuario.Rol.ADMIN

#Permiso específico para editar un pedido dependiendo del estado. Si es notificado, no se puede 
def puede_editar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return True
    if pedido.estado_notificacion == Pedido.EstadoNotificacion.NOTIFICADO:
        return False
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        return pedido.estado_comercial == Pedido.EstadoComercial.PENDIENTE
    if rol == PerfilUsuario.Rol.LOGISTICA:
        return pedido.estado_comercial == Pedido.EstadoComercial.APROBADO
    return False

def queryset_visible(usuario, queryset):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
          return queryset

    if rol == PerfilUsuario.Rol.EJECUTIVO:
        perfil = getattr(usuario, "perfil", None)
        return queryset.filter(
            estado_comercial=Pedido.EstadoComercial.PENDIENTE,
            ejecutivo__codigo_sap=perfil.codigo_empleado_sap,
        )

    if rol == PerfilUsuario.Rol.LOGISTICA:
        return queryset.filter(estado_comercial=Pedido.EstadoComercial.APROBADO)
    return queryset.none()