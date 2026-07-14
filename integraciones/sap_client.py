import requests
from django.conf import settings

""""Este archivo se encarga de almacenar todas las funciones con las que se llama a SAP"""

def obtener_cookies_sap():
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

def agregar_rango_fechas(filtro_base, campo_fecha, after=None, before=None):
    filtros = [f"({filtro_base})"]

    if after:
        filtros.append(f"{campo_fecha} ge '{after}'")

    if before:
        filtros.append(f"{campo_fecha} le '{before}'")
    
    return " and ".join(filtros)

def obtener_business_partner(card_code, cookies):
    r = requests.get(
        f"{settings.SAP_URL}/BusinessPartners('{card_code}')",
        params={"$select": "CardCode,CardName,EmailAddress,Phone1,ContactEmployees"},
        cookies=cookies,
        timeout=60,
    )
    if r.status_code != 200:
        return {}
    return r.json()

def obtener_todas_las_paginas(url, params, cookies):
      resultados = []

      while url:
          r = requests.get(url, params=params, cookies=cookies, timeout=120)
          r.raise_for_status()
          datos = r.json()

          resultados.extend(datos.get("value", []))

          siguiente = datos.get("odata.nextLink")
          if not siguiente:
              break

          url = f"{settings.SAP_URL}/{siguiente}"
          params = None  # el nextLink ya trae $skip incluido en la URL

      return resultados