import requests, base64
from django.conf import settings
from utils import validar_rut, quitar_tildes

#Permite dividir en dos el listado de los N° de pedidos, para cuando exceden el
#Tamaño máximo del campo referencia, empezando a usar referencia2

def particionar_referencias(numeros_pedido):
    texto_completo = "/".join(numeros_pedido)

    if len(texto_completo) <= 24:
        return texto_completo, ""

    partes = texto_completo.split("/")
    primera_parte = ""
    segunda_parte = ""

    for parte in partes:
        candidato = f"{primera_parte}/{parte}" if primera_parte else parte
        if len(candidato) <= 24:
            primera_parte = candidato
        else:
            candidato_segunda = f"{segunda_parte}/{parte}" if segunda_parte else parte
            if len(candidato_segunda) > 35:
                return None, None
            segunda_parte = candidato_segunda

    if not primera_parte:
        return None, None

    return primera_parte, segunda_parte

#Función que construye el Payload que va hacia Chibra
def documentar_envio(pedidos, bultos, destinatario, datos_courier):
    numeros_pedido = [p.num_pedido for p in pedidos]
    referencia_1, referencia_2 = particionar_referencias(numeros_pedido)
    if referencia_1 is None:
        raise ValueError("[!] Error: Demasiados pedidos para documentar en un solo envío (no caben las referencias).")

    if not validar_rut(destinatario["rut"]):
        raise ValueError(f"[!] Error: RUT inválido para documentar el envío: {destinatario['rut']}")

    numero_bultos = sum(bulto["cantidad"] for bulto in bultos)
    kilos = sum(bulto["peso"] * bulto["cantidad"] for bulto in bultos)

    tipos_bulto = []
    for bulto in bultos:
        tipos_bulto.append({
            "TIPO": bulto.get("tipo", "CAJA"),
            "CANTIDAD": bulto["cantidad"],
            "ALTO": bulto.get("alto", 0),
            "ANCHO": bulto.get("ancho", 0),
            "LARGO": bulto.get("largo", 0),
            "PESO": bulto["peso"],
            "TIPO_CONTENIDO": bulto.get("tipo_contenido", "SECO"),
        })

    envio = {
        "CLIENTE_REMITENTE": settings.CHIBRA_CLIENTE_REMITENTE,
        "CENTRO_REMITENTE": datos_courier.get("centro"),
        "NIF_DESTINATARIO": destinatario["rut"],
        "NOMBRE_DESTINATARIO": destinatario["nombre"],
        "DIRECCION_DESTINATARIO": destinatario["direccion"],
        "PAIS_DESTINATARIO": "CL",
        "POBLACION_DESTINATARIO": quitar_tildes(destinatario["comuna"]),
        "TELEFONO_CONTACTO_DESTINATARIO": destinatario["telefono"].lstrip("'"),
        "PERSONA_CONTACTO_DESTINATARIO": destinatario["nombre"],
        "EMAIL_DESTINATARIO": destinatario["email"],
        "NUMERO_BULTOS": numero_bultos,
        "CODIGO_PRODUCTO_SERVICIO": datos_courier.get("servicio"),
        "KILOS": kilos,
        "TIPO_PORTES": "P",
        "CLIENTE_REFERENCIA": referencia_1,
        "REFERENCIA2": referencia_2,
        "IMPRIMIR_ETIQUETA": "S",
        "IMPORTE_VALOR_DECLARADO": datos_courier.get("valor_declarado", 0),
        "ENVIO_DEFINITIVO": "N",
        "TIPOS_BULTO": tipos_bulto,
    }

    if datos_courier.get("volumen_total"):
        envio["VOLUMEN"] = datos_courier["volumen_total"]

    if datos_courier.get("observaciones"):
        envio["OBSERVACIONES1"] = datos_courier["observaciones"]

    documentos = datos_courier.get("documentos") or []
    tipos_documento = [
        {"TIPO": doc["tipo"], "REFERENCIA": doc["referencia"]}
        for doc in documentos
        if doc.get("tipo") and doc.get("referencia")
    ]
    if tipos_documento:
        envio["TIPOS_DOCUMENTO"] = tipos_documento

    payload = {"DOCUMENTAR_ENVIOS": {"VERSION": "6", "DOCUMENTAR_ENVIO": [envio]}}

    respuesta = requests.post(
        f"{settings.CHIBRA_BASE_URL}/gts/seam/resource/restv1/auth/documentarEnvio/json",
        auth=(settings.CHIBRA_USER, settings.CHIBRA_PASSWORD),
        json=payload,
        timeout=30,
    )
    respuesta.raise_for_status()
    datos_respuesta = respuesta.json()
    resultado = (datos_respuesta[0] if isinstance(datos_respuesta, list) and datos_respuesta else {}).get("respuestaDocuemtarEnvio", {})

    if resultado.get("resultado") != "OK":
        raise ValueError(f"[!] Error de Chibra: {resultado.get('mensaje', 'sin detalle')}")

    return {"numero_envio": str(resultado.get("numero_envio", ""))}

#Chibra ya devuelve la etiqueta dentro de documentar_envio (IMPRIMIR_ETIQUETA="S"), pero esa llamada
#no se puede repetir (crea el envío de nuevo). Para volver a obtenerla después se usa etiquetarService
#con ETIQUETAR="R" (reetiquetar) — mismo courier, servicio distinto, ver ws_chibra_05_etiquetar.md.
def obtener_etiqueta(centro, expedicion):
    payload = {
        "ETIQUETAS": {
            "VERSION": "5",
            "ETIQUETA": [{
                "CLIENTE": settings.CHIBRA_CLIENTE_REMITENTE,
                "CENTRO": centro,
                "EXPEDICION": expedicion,
                "ETIQUETAR": "R",
                "FORMATO": "PDF",
            }]
        }
    }

    respuesta = requests.post(
        f"{settings.CHIBRA_BASE_URL}/gts/seam/resource/restv1/auth/etiquetarService/etiquetar",
        auth=(settings.CHIBRA_USER, settings.CHIBRA_PASSWORD),
        json=payload,
        timeout=30,
    )
    respuesta.raise_for_status()
    datos_respuesta = respuesta.json()
    resultado = (datos_respuesta[0] if isinstance(datos_respuesta, list) and datos_respuesta else {}).get("respuestaEtiquetar", {})

    if resultado.get("resultado") != "OK":
        raise ValueError(f"[!] Error de Chibra al generar etiqueta: {resultado.get('mensaje', 'sin detalle')}")

    return base64.b64decode(resultado["etiqueta"])

