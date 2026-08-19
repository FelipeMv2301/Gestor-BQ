from utils import Courier
from integraciones import chibra_client, moveup_client, starken_client

"""
Documentos descargables por courier (etiqueta, evidencia de entrega, etc.).

Registro por (courier, tipo). Cada courier se inscribe solo en los tipos que soporta. Cada función
recibe la orden de transporte y devuelve una lista de bytes (un archivo por bulto/encargo).
"""

DOCUMENTOS_COURIER = {
    Courier.STARKEN: {
        "etiqueta": lambda envio: starken_client.generar_etiqueta(envio.orden_transporte),
        # "evidencia_entrega": starken_client.obtener_evidencia_entrega,  # cuando exista (HU-ST4.3)
    },
    Courier.MOVEUP: {
        "etiqueta": lambda envio: [moveup_client.obtener_etiqueta(envio.orden_transporte)],
    },
    Courier.CHIBRA: {
        "etiqueta": lambda envio: [chibra_client.obtener_etiqueta(envio.datos_courier.get("centro"), envio.orden_transporte)],
    },
}

ETIQUETAS_TIPO_DOCUMENTO = {
    "etiqueta": "Etiqueta de envío",
    "evidencia_entrega": "Evidencia de entrega",
}

def documentos_disponibles(courier):
    return list(DOCUMENTOS_COURIER.get(courier, {}).keys())

def generar_documento(envio, tipo):
    fn = DOCUMENTOS_COURIER.get(envio.courier, {}).get(tipo)
    if not fn:
        raise ValueError(f"[!] Error: {envio.courier} no tiene disponible el documento '{tipo}'.")
    return fn(envio)