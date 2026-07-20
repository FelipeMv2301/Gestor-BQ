from .models import EnvioCourier
from pedidos.models import Pedido

def despachar_pedidos(pedidos, courier, datos_courier):
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
        
    resultado = {"orden_transporte": "TEST-0001"}

    envio = EnvioCourier.objects.create(
        courier=courier,
        datos_courier=datos_courier,
        orden_transporte=resultado["orden_transporte"],
        estado=EnvioCourier.Estado.DESPACHADO,
    )
    for pedido in pedidos:
        pedido.envio = envio
        pedido.save(update_fields=["envio"])
    
    return envio
