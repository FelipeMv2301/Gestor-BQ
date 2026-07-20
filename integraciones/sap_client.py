import requests
from django.conf import settings

""""Este archivo se encarga de almacenar todas las funciones con las que se llama a SAP"""

#Obtiene las cookies de SAP (session y routeid) y genera el reintento mediante b1session_vencido
def obtener_cookies_sap(b1session_vencido=None):

    if b1session_vencido:
        requests.post(
            f"{settings.TOKEN_SAP_BQ_URL}/session/invalidate",
            json={
                "service_name": settings.TOKEN_SAP_BQ_USER,
                "password": settings.TOKEN_SAP_BQ_PASS,
                "b1session": b1session_vencido,
            },
            timeout=120,
        )

    resp = requests.post(
        f"{settings.TOKEN_SAP_BQ_URL}/session",
        json = {
            "service_name": settings.TOKEN_SAP_BQ_USER,
            "password": settings.TOKEN_SAP_BQ_PASS,
        },
        timeout=120,
    )
    resp.raise_for_status()
    sesion = resp.json()

    cookies = {"B1SESSION": sesion["b1session"]}
    if sesion.get("routeid"):
        cookies["ROUTEID"] = sesion["routeid"]

    return cookies


#Crea la llamada al endpoint con los parámetros que devuelvan las funciones.
def solicitar_sap(metodo, url, cookies, params=None, timeout=60):
    respuesta = requests.request(metodo, url, params=params, cookies=cookies, timeout=timeout)

    if respuesta.status_code == 401:
        cookies = obtener_cookies_sap(b1session_vencido=cookies.get("B1SESSION"))
        respuesta = requests.request(metodo, url, params=params, cookies=cookies, timeout=timeout)

    return respuesta, cookies


def agregar_rango_fechas(filtro_base, campo_fecha, after=None, before=None):
    filtros = [f"({filtro_base})"]

    if after:
        filtros.append(f"{campo_fecha} ge '{after}'")

    if before:
        filtros.append(f"{campo_fecha} le '{before}'")
    
    return " and ".join(filtros)


def obtener_business_partner(card_code, cookies):
    url = f"{settings.SAP_URL}/BusinessPartners('{card_code}')"
    params = {"$select": "CardCode,CardName,EmailAddress,Phone1,ContactEmployees"}

    respuesta, cookies_actualizadas = solicitar_sap("GET", url, cookies, params=params)
    if respuesta.status_code != 200:
        return {}
    return respuesta.json()


def obtener_todas_las_paginas(url, params, cookies):
    resultados = []

    while url:
        respuesta, cookies = solicitar_sap("GET", url, cookies, params=params)
        respuesta.raise_for_status()
        datos = respuesta.json()

        resultados.extend(datos.get("value", []))

        siguiente = datos.get("odata.nextLink")
        if not siguiente:
            break

        url = f"{settings.SAP_URL}/{siguiente}"
        params = None  # el nextLink ya trae $skip incluido en la URL

    return resultados