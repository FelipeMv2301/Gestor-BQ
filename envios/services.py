from .models import EnvioCourier
from integraciones import chibra_client
from pedidos.models import Pedido
from pedidos.services  import notificar_pedido
from django.db import transaction
from utils import Courier

#Valida que un grupo de pedidos pueda agruparse en un solo despacho. Se usa apenas se selecciona
#el grupo (para fallar rápido, antes de mostrar el formulario) y de nuevo al confirmar el despacho.
#Devuelve el courier común (ya validado) para no volver a inferirlo con pedidos[0].
def validar_pedidos_para_despacho(pedidos):
    if not pedidos:
        raise ValueError("[!] Error: Selecciona al menos un pedido")

    destinatarios = {p.rut for p in pedidos}
    if len(destinatarios) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados tienen destinatarios distintos") #Revisar validación (puede causar errores innecesarios)

    couriers = {p.courier for p in pedidos}
    if len(couriers) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados no usan el mismo courier (puedes editarlo)")
    courier = couriers.pop()
    if not courier:
        raise ValueError("[!] Error: Los pedidos seleccionados no tienen courier asignado (puedes editarlo)")

    servicios = {p.servicio_courier_codigo for p in pedidos if p.servicio_courier_codigo}
    if len(servicios) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados detectaron distintos servicios de courier (ej. Express y Terrestre) — revisa antes de agrupar")

    for pedido in pedidos:
        if pedido.estado_comercial != Pedido.EstadoComercial.APROBADO:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} no está APROBADO.")
        if pedido.envio_id is not None:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} ya tiene un envío asignado.")

    return courier

def despachar_pedidos(pedidos, courier, bultos, destinatario, datos_courier, usuario):
    validar_pedidos_para_despacho(pedidos)   # re-valida por seguridad, aunque la vista ya haya chequeado

    if courier == Courier.CHIBRA:
        resultado = chibra_client.documentar_envio(pedidos, bultos, destinatario, datos_courier)
    else:
        raise ValueError(f"[!] Error: No existe integración disponible para el courier {courier}.")
        
    with transaction.atomic():
        envio = EnvioCourier.objects.create(
            courier=courier,
            datos_courier=datos_courier,
            orden_transporte=resultado["numero_envio"],
            estado=EnvioCourier.Estado.DESPACHADO,
        )

        for pedido in pedidos:
            pedido.envio = envio
            pedido.save(update_fields=["envio"])

    notificaciones_fallidas = []
    for pedido in pedidos:
        try:
            notificar_pedido(pedido, usuario)
        except (PermissionError, ValueError) as exc:
            notificaciones_fallidas.append((pedido, str(exc)))

    return envio, notificaciones_fallidas
