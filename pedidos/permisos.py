from cuentas.models import PerfilUsuario
from .models import Pedido

"""
Manejar los permisos de cada usuario y por funcionalidades.
1. Muestra los datos dependiendo de que tipo de usuario eres.
2. Permite la edición / cancelación de pedidos dependiendo del estado del pedido y de tu rol.
3. Creación de querysets para diferentes funcionalidades.
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

#Permiso para reingresar un pedido anulado (solo Admin)
def puede_reingresar(usuario):
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

def queryset_pedidos_ejecutivo(usuario, estado=None):
    perfil = getattr(usuario, "perfil", None)
    query = Pedido.objects.filter(ejecutivo__codigo_sap=perfil.codigo_empleado_sap)

    if estado:
        query = query.filter(estado_comercial=estado)
    return query

#Permiso para disparar la notificación al cliente
def puede_notificar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol not in (PerfilUsuario.Rol.LOGISTICA, PerfilUsuario.Rol.ADMIN):
        return False
    return pedido.estado_comercial == Pedido.EstadoComercial.APROBADO

def queryset_para_ver(usuario):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return Pedido.objects.all()
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        perfil = getattr(usuario, "perfil", None)
        return Pedido.objects.filter(ejecutivo__codigo_sap=getattr(perfil, "codigo_empleado_sap", None))
    if rol == PerfilUsuario.Rol.LOGISTICA:
        return Pedido.objects.filter(estado_comercial=Pedido.EstadoComercial.APROBADO)
    return Pedido.objects.none()

def es_logistica(usuario):
    return obtener_rol(usuario) in (PerfilUsuario.Rol.LOGISTICA, PerfilUsuario.Rol.ADMIN)

"""
Campos que los usuarios podran editar en el proyecto
"""

CAMPOS_EDITABLES_EJECUTIVO = [
    "rut", "razon_social",
    "nombre_contacto", "telefono_contacto", "email_contacto",
    "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
    "courier",
    "observaciones",
]

CAMPOS_EDITABLES_LOGISTICA = [
    "rut", "razon_social",
    "nombre_contacto", "telefono_contacto", "email_contacto",
    "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
    "courier", "retirar_en",
    "observaciones",
]

def campos_editables(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return None  # sin restricción

    if rol == PerfilUsuario.Rol.EJECUTIVO:
        return CAMPOS_EDITABLES_EJECUTIVO
    
    if rol == PerfilUsuario.Rol.LOGISTICA:
        return CAMPOS_EDITABLES_LOGISTICA

    return []