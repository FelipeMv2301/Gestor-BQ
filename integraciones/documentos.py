from utils import Courier
from integraciones import moveup_client, starken_client

"""
Documentos descargables por courier (etiqueta, evidencia de entrega, etc.).

Registro por (courier, tipo). Cada courier se inscribe solo en los tipos que soporta. Cada función
recibe la orden de transporte y devuelve una lista de bytes (un archivo por bulto/encargo).
"""

DOCUMENTOS_COURIER = {
    Courier.STARKEN: {
        "etiqueta": starken_client.generar_etiqueta,
        # "evidencia_entrega": starken_client.obtener_evidencia_entrega,  # cuando exista (HU-ST4.3)
    },
    Courier.MOVEUP: {
        "etiqueta": lambda orden_transporte: [moveup_client.obtener_etiqueta(orden_transporte)],
    },
}

ETIQUETAS_TIPO_DOCUMENTO = {
    "etiqueta": "Etiqueta de envío",
    "evidencia_entrega": "Evidencia de entrega",
}

def documentos_disponibles(courier):
    return list(DOCUMENTOS_COURIER.get(courier, {}).keys())

def generar_documento(courier, tipo, orden_transporte):
    fn = DOCUMENTOS_COURIER.get(courier, {}).get(tipo)
    if not fn:
        raise ValueError(f"[!] Error: {courier} no tiene disponible el documento '{tipo}'.")
    return fn(orden_transporte)