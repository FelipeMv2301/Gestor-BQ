"""Helpers para construir objetos de prueba (usuarios con rol, ejecutivos, pedidos)."""
from django.contrib.auth.models import User
from cuentas.models import PerfilUsuario
from ejecutivos.models import Ejecutivo
from pedidos.models import Pedido


def crear_usuario(email, rol=None, codigo_sap=None):
    """Crea un User; el signal ya le crea el PerfilUsuario, acá le fijamos rol/código.
    Se modifica el objeto perfil (no un .update de queryset) para no dejar cache viejo en user.perfil.
    Mantiene escalar y M2M `ejecutivos` consistentes (el signal pudo poblar la M2M al crear el user)."""
    user = User.objects.create(username=email, email=email)
    perfil = user.perfil
    perfil.rol = rol
    perfil.codigo_empleado_sap = codigo_sap
    perfil.save()
    perfil.ejecutivos.clear()
    if codigo_sap is not None:
        ejecutivo = Ejecutivo.objects.filter(codigo_sap=codigo_sap).first()
        if ejecutivo:
            perfil.ejecutivos.add(ejecutivo)
    return user


def crear_ejecutivo(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True, es_ont=False):
    return Ejecutivo.objects.create(codigo_sap=codigo_sap, nombre=nombre, email=email, activo=activo, es_ont=es_ont)


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
