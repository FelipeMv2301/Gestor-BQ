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

#Permiso específico para pasar un pedido a pedidosRechazados. Admin siempre; el ejecutivo dueño
#solo hasta que se despache a courier (mismo corte que puede_editar).
def puede_rechazar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return True
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        return responsable_del_pedido(usuario, pedido) and pedido.envio_id is None
    return False

#Permiso para reingresar un pedido anulado (solo Admin)
def puede_reingresar(usuario, rechazado):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return True
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        return rechazado.snapshot.get("ejecutivo") == _ejecutivo_pk(usuario)
    return False

#Permiso específico para editar un pedido. Ejecutivo: hasta que se despache a courier (envio_id).
#Logística: hasta que se notifique al cliente. Si es notificado, nadie salvo Admin.
def puede_editar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return True
    if pedido.estado_notificacion == Pedido.EstadoNotificacion.NOTIFICADO:
        return False
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        return pedido.envio_id is None
    if rol == PerfilUsuario.Rol.LOGISTICA:
        return True
    return False

def queryset_visible(usuario, queryset):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
          return queryset

    if rol == PerfilUsuario.Rol.EJECUTIVO:
        perfil = getattr(usuario, "perfil", None)
        return queryset.filter(ejecutivo__codigo_sap=perfil.codigo_empleado_sap)

    if rol == PerfilUsuario.Rol.LOGISTICA:
        return queryset
    return queryset.none()

def queryset_pedidos_ejecutivo(usuario):
    perfil = getattr(usuario, "perfil", None)
    return Pedido.objects.filter(ejecutivo__codigo_sap=perfil.codigo_empleado_sap)

#Permiso para editar el courier inline desde la tabla (mismo criterio que la edición completa,
#más el chequeo de que "courier" esté en los campos que el rol puede tocar)
def puede_editar_courier(usuario, pedido):
    if not puede_editar(usuario, pedido):
        return False
    permitidos = campos_editables(usuario, pedido)
    return permitidos is None or "courier" in permitidos

#Permiso para disparar la notificación al cliente
def puede_notificar(usuario, pedido):
    rol = obtener_rol(usuario)
    if rol not in (PerfilUsuario.Rol.LOGISTICA, PerfilUsuario.Rol.ADMIN):
        return False
    return pedido.estado_comercial == Pedido.EstadoComercial.APROBADO

#Permiso para despachar un pedido individual a courier desde el detalle
def puede_despachar(usuario, pedido):
    if obtener_rol(usuario) not in (PerfilUsuario.Rol.LOGISTICA, PerfilUsuario.Rol.ADMIN):
        return False
    return (
        pedido.estado_comercial == Pedido.EstadoComercial.APROBADO
        and pedido.envio_id is None
        and bool(pedido.courier)
    )

def queryset_para_ver(usuario):
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return Pedido.objects.all()
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        perfil = getattr(usuario, "perfil", None)
        return Pedido.objects.filter(ejecutivo__codigo_sap=getattr(perfil, "codigo_empleado_sap", None))
    if rol == PerfilUsuario.Rol.LOGISTICA:
        return Pedido.objects.all()
    return Pedido.objects.none()

def es_logistica(usuario):
    return obtener_rol(usuario) in (PerfilUsuario.Rol.LOGISTICA, PerfilUsuario.Rol.ADMIN)

def es_admin(usuario):
    return obtener_rol(usuario) == PerfilUsuario.Rol.ADMIN

# pk del Ejecutivo del usuario (para acotar rechazados a "los suyos")
#Básicamente ayuda a que las funciones como rechazar pedido, sigan vinculadas al ejecutivo comercial del pedido y así los cambios sean visibles para él
def _ejecutivo_pk(usuario):
    from ejecutivos.models import Ejecutivo
    codigo = getattr(getattr(usuario, "perfil", None), "codigo_empleado_sap", None)
    if codigo is None:
        return None
    ejec = Ejecutivo.objects.filter(codigo_sap=codigo).first()
    return ejec.pk if ejec else None

def queryset_rechazados(usuario):
    from pedidosRechazados.models import PedidoRechazado
    rol = obtener_rol(usuario)
    if rol == PerfilUsuario.Rol.ADMIN:
        return PedidoRechazado.objects.all()
    if rol == PerfilUsuario.Rol.EJECUTIVO:
        pk = _ejecutivo_pk(usuario)
        return PedidoRechazado.objects.filter(snapshot__ejecutivo=pk) if pk else PedidoRechazado.objects.none()
    return PedidoRechazado.objects.none()

"""
Campos que los usuarios podran editar en el proyecto
"""

CAMPOS_EDITABLES_EJECUTIVO = [
    "rut", "razon_social",
    "nombre_contacto", "telefono_contacto", "email_contacto",
    "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
    "tipo_entrega", "courier",
    "observaciones",
]

CAMPOS_EDITABLES_LOGISTICA = [
    "rut", "razon_social",
    "nombre_contacto", "telefono_contacto", "email_contacto",
    "direccion_calle", "direccion_depto", "direccion_comuna", "direccion_ciudad",
    "tipo_entrega", "courier", "retirar_en",
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