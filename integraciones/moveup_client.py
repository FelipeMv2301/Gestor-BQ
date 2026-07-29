import requests, base64
from django.conf import settings

"""Este archivo se encarga de almacenar todas las funciones con las que se llama a MoveUP"""

#Equivalente al enum "PackageSize" de la doc de MoveUP
PACKAGE_SIZE_SOBRE = 1
PACKAGE_SIZE_CAJA = 2


#Arma los headers comunes a toda llamada a MoveUP — placeholder hasta resolver cómo se obtiene
#el Access Token (fijo en .env, o vía un endpoint de login que haya que renovar como en sap_client.py)
def _headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {settings.MOVEUP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def crear_paquetes(paquetes):
    respuesta = requests.post(
        f"{settings.MOVEUP_BASE_URL}/integrations/packages",
        headers=_headers(),
        json=paquetes,
        timeout=60,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("status") != 200:
        raise ValueError(f"[!] Error de MoveUP: {datos.get('message', 'sin detalle')}")
    
    return datos["createdPackages"]

def consultar_envios(id_paquete=None, estado=None, desde=None, hasta=None):
    params = {}
    if id_paquete:
        params["id"] = id_paquete
    
    if estado:
        params["status"] = estado
    
    if desde:
        params["startDate"] = desde
    
    if hasta:
        params["endDate"] = hasta

    respuesta = requests.get(
        f"{settings.MOVEUP_BASE_URL}/integrations/packages",
        headers=_headers(),
        params=params,
        timeout=60
    )

    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("status") != 200:
        raise ValueError(f"[!] Error de MoveUP: {datos.get('message', 'sin detalle')}")

    return datos["response"]

def obtener_etiqueta(id_paquete):
    respuesta = requests.get(
        f"{settings.MOVEUP_BASE_URL}/integrations/packages/ticket/{id_paquete}",
        headers=_headers(),
        timeout=60,
    )

    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("status") != 200:
        raise ValueError(f"[!] Error de MoveUP: {datos.get('message', 'sin detalle')}")

    return base64.b64decode(datos["pdfBase64"])
