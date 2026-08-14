import requests, base64
from django.conf import settings
from utils import validar_rut, normalizar_telefono_cl

TIPO_ENTREGA_AGENCIA = 1 #Para envíos a agencia de starken
TIPO_ENTREGA_DOMICILIO = 2 #Para envíos a domicilio del cliente
TIPO_ENCARGO_DEFAULT = "29" #Se desconoce su uso
TIPO_SALIDA_BASE64_10X10 = 6 #Determinar el tamaño de la etiqueta

"""
Helpers
"""
# Sirve para gestionar los documentos (maximo 5) que se pueden incorporar en starken
def _referencias_documentos(documentos):
    #Starken no acepta una lista de documentos: son 5 campos fijos con nombre (tipoDocumentoN/
    #numeroDocumentoN/generaEtiquetaDocumentoN, N del 1 al 5), no un arreglo.
    if len(documentos) > 5:
        raise ValueError(f"[!] Error: Starken admite máximo 5 documentos de referencia por OF (se enviaron {len(documentos)}).")

    campos = {}
    for numero_slot in range(1, 6):
        documento = documentos[numero_slot - 1] if numero_slot <= len(documentos) else None
        campos[f"tipoDocumento{numero_slot}"] = documento["tipo"] if documento else ""
        campos[f"numeroDocumento{numero_slot}"] = documento["numero"] if documento else ""
        campos[f"generaEtiquetaDocumento{numero_slot}"] = "N"
    return campos

def emitir_of(pedidos, bultos, destinatario, datos_courier):
    numero_bultos = sum(b["cantidad"] for b in bultos)
    kilos = sum(b["peso"] * b["cantidad"] for b in bultos)
    #Multibultos (FAQ del manual): sumar UNA dimensión y tomar el máximo de las otras dos.
    largo = sum(float(b.get("largo") or 0) for b in bultos)
    ancho = max((float(b.get("ancho") or 0) for b in bultos), default=0)
    alto = max((float(b.get("alto") or 0) for b in bultos), default=0)

    codigo_agencia = datos_courier.get("codigo_agencia_destino")
    tipo_entrega = TIPO_ENTREGA_AGENCIA if codigo_agencia else TIPO_ENTREGA_DOMICILIO
    comuna_destino = f"@{codigo_agencia}" if codigo_agencia else destinatario["comuna"]

    rut_cuerpo, _, rut_dv = destinatario["rut"].partition("-")

    if not validar_rut(destinatario["rut"]):
        raise ValueError(f"[!] Error: RUT inválido para emitir la OF en Starken: {destinatario['rut']}")

    payload = {
        "rutEmpresaEmisora": settings.STARKEN_RUT_EMPRESA_EMISORA,
        "rutUsuarioEmisor": settings.STARKEN_RUT_USUARIO_EMISOR,
        "claveUsuarioEmisor": settings.STARKEN_CLAVE_USUARIO_EMISOR,
        "rutRemitente": settings.STARKEN_RUT_REMITENTE,
        "dvRemitente": settings.STARKEN_DV_REMITENTE,
        "nombreRazonSocialRemitente": settings.STARKEN_RAZON_SOCIAL_REMITENTE,
        "apellidoPaternoRemitente": ".",
        "apellidoMaternoRemitente": ".",
        "direccionRemitente": settings.STARKEN_DIRECCION_REMITENTE,
        "numeracionDireccionRemitente": settings.STARKEN_NUMERACION_DIRECCION_REMITENTE,
        "departamentoRemitente": "",
        "emailRemitente": settings.STARKEN_EMAIL_REMITENTE,
        "telefonoRemitente": settings.STARKEN_TELEFONO_REMITENTE,
        "comunaRemitente": settings.STARKEN_COMUNA_REMITENTE,
        "rutDestinatario": rut_cuerpo,
        "dvRutDestinatario": rut_dv,
        #El manual separa nombre/apellidoPaterno/apellidoMaterno del destinatario; nosotros solo
        #tenemos el nombre completo en un string (mismo dato que usan Chibra/MoveUP). Se manda todo
        #en nombreRazonSocialDestinatario y "." en los apellidos — confirmar en QA si Starken lo acepta así.
        "nombreRazonSocialDestinatario": destinatario["nombre"],
        "apellidoPaternoDestinatario": ".",
        "apellidoMaternoDestinatario": ".",
        "direccionDestinatario": destinatario["direccion"],
        "numeracionDireccionDestinatario": destinatario.get("numero") or "",
        "departamentoDireccionDestinatario": destinatario.get("depto") or "",
        "comunaDestino": comuna_destino,
        "telefonoDestinatario": normalizar_telefono_cl(destinatario.get("telefono") or ""),
        "emailDestinatario": destinatario.get("email") or "",
        "nombreContactoDestinatario": destinatario["nombre"],
        "tipoEntrega": tipo_entrega,
        "tipoPago": "2",
        "numeroCtaCte": settings.STARKEN_NUMERO_CTA_CTE,
        "dvNumeroCtaCte": settings.STARKEN_DV_NUMERO_CTA_CTE,
        "centroCostoCtaCte": settings.STARKEN_CENTRO_COSTO_CTA_CTE,
        "valorDeclarado": str(int(datos_courier.get("valor_declarado") or 0)),
        "contenido": datos_courier.get("contenido") or "MERCADERIA",
        "kilosTotal": str(kilos),
        "alto": str(alto),
        "ancho": str(ancho),
        "largo": str(largo),
        "tipoServicio": datos_courier.get("servicio") or "0",
        **_referencias_documentos(datos_courier.get("documentos") or []),
        "tipoEncargo1": TIPO_ENCARGO_DEFAULT,
        "cantidadEncargo1": str(numero_bultos),
        "tipoEncargo2": "", "cantidadEncargo2": "",
        "tipoEncargo3": "", "cantidadEncargo3": "",
        "tipoEncargo4": "", "cantidadEncargo4": "",
        "tipoEncargo5": "", "cantidadEncargo5": "",
        "observacion": datos_courier.get("observaciones") or "",
    }

    respuesta = requests.post(settings.STARKEN_BASE_URL, json=payload, timeout=30)
    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("codigoError") != 0:
        raise ValueError(f"[!] Error de Starken: {datos.get('descripcionError', 'sin detalle')}")

    #nroOrdenFlete viene en notación científica (ej. 2.22607751E8) — convertir antes de guardar.
    return {"numero_orden_flete": str(int(float(datos["nroOrdenFlete"])))}

def generar_etiqueta(numero_orden_flete, tipo_salida=TIPO_SALIDA_BASE64_10X10):
    respuesta = requests.post(
        settings.STARKEN_ETIQUETA_URL,
        auth=(settings.STARKEN_ETIQUETA_USER, settings.STARKEN_ETIQUETA_PASSWORD),
        params={"ordenFlete": numero_orden_flete, "tipoSalida": tipo_salida},
        timeout=30,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("status") != 200:
        raise ValueError(f"[!] Error de Starken al generar etiqueta: {datos.get('message', 'sin detalle')}")

    #data es un arreglo de strings Base64 (uno por bulto/encargo, ver manual sección "Generación de etiqueta").
    return [base64.b64decode(etiqueta) for etiqueta in datos["data"]]