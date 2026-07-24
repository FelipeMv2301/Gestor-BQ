from .models import EnvioCourier
from integraciones import chibra_client
from pedidos.models import Pedido
from pedidos.services  import notificar_pedido
from django.db import transaction

def despachar_pedidos(pedidos, courier, bultos, destinatario, datos_courier, usuario):
    if not pedidos:
        raise ValueError("[!] Error: Selecciona al menos un pedido")
    
    destinatarios = {p.rut for p in pedidos}
    if len(destinatarios) > 1:
        raise ValueError("[!] Error: Los pedidos seleccionados tienen destinatarios distintos") #Revisar validación (puede causar errores innecesarios)
    
    couriers = {p.courier for p in pedidos}
    if couriers != {courier}:
        raise ValueError("[!] Error: Los pedidos seleccionados no usan el mismo courier (puedes editarlo)")
    
    for pedido in pedidos:
        if pedido.estado_comercial != Pedido.EstadoComercial.APROBADO:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} no está APROBADO.")
        if pedido.envio_id is not None:
            raise ValueError(f"Pedido N° {pedido.origen}-{pedido.num_pedido} ya tiene un envío asignado.")
        
    if courier == Pedido.Courier.CHIBRA:
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
