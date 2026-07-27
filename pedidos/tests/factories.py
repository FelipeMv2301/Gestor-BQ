"""Helpers para construir objetos de prueba (usuarios con rol, ejecutivos, pedidos)."""
from django.contrib.auth.models import User
from cuentas.models import PerfilUsuario
from ejecutivos.models import Ejecutivo
from pedidos.models import Pedido


def crear_usuario(email, rol=None, codigo_sap=None):
    """Crea un User; el signal ya le crea el PerfilUsuario, acá le fijamos rol/código.
    Se modifica el objeto perfil (no un .update de queryset) para no dejar cache viejo en user.perfil."""
    user = User.objects.create(username=email, email=email)
    perfil = user.perfil
    perfil.rol = rol
    perfil.codigo_empleado_sap = codigo_sap
    perfil.save()
    return user


def crear_ejecutivo(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True):
    return Ejecutivo.objects.create(codigo_sap=codigo_sap, nombre=nombre, email=email, activo=activo)


def crear_pedido(num="1000", **kwargs):
    datos = dict(
        origen=Pedido.Origen.SAP,
        num_pedido=num,
        tipo_entrega=Pedido.TipoEntrega.DESPACHO,
        estado_comercial=Pedido.EstadoComercial.PENDIENTE,
        rut="11111111-1",
    )
    datos.update(kwargs)
    return Pedido.objects.create(**datos)
