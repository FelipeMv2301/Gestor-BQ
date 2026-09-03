import requests
from django.conf import settings
from integraciones.sap_client import obtener_cookies_sap, obtener_todas_las_paginas
from .models import Ejecutivo
from cuentas.models import PerfilUsuario


def sincronizar_ejecutivos_desde_sap():
    cookies = obtener_cookies_sap()

    datos_sap = obtener_todas_las_paginas(
        f"{settings.SAP_URL}/SalesPersons",
        {"$select": "SalesEmployeeCode,SalesEmployeeName,Email,Active"},
        cookies,
    )

    creados = 0
    actualizados = 0

    for sap in datos_sap:
        codigo = sap.get("SalesEmployeeCode")
        if codigo is None or codigo < 0:
            continue

        ejecutivo, creado = Ejecutivo.objects.update_or_create(
            codigo_sap=codigo,
            defaults={
                "nombre": sap.get("SalesEmployeeName") or "",
                "email": sap.get("Email") or "",
                "activo": sap.get("Active") == "tYES",
            },
        )

        if creado:
            creados += 1
        else:
            actualizados += 1

    codigos_vistos = set()
    for sap in datos_sap:
        codigo = sap.get("SalesEmployeeCode")
        if codigo is not None:
            codigos_vistos.add(codigo)

    marcados_inactivos = (
      Ejecutivo.objects
      .exclude(codigo_sap__in=codigos_vistos)
      .filter(activo=True)
      .update(activo=False)
    )

    #Update a perfiles
    perfiles_actualizados = 0
    for perfil in PerfilUsuario.objects.filter(codigo_empleado_sap__isnull=True).select_related("usuario"):
        ejecutivo = Ejecutivo.objects.filter(email=perfil.usuario.email, activo=True).first()
        if not ejecutivo:
            continue
        #El escalar es 1:1 (unique=True en DB, legacy): solo se rellena si ningún otro perfil lo tiene
        #ya. La M2M sí permite que varios perfiles compartan el mismo código (decisión de Felipe
        #2026-09-02) — se vincula siempre, esté o no ocupado el escalar.
        if not PerfilUsuario.objects.filter(codigo_empleado_sap=ejecutivo.codigo_sap).exists():
            perfil.codigo_empleado_sap = ejecutivo.codigo_sap
            perfil.save(update_fields=["codigo_empleado_sap"])
        perfil.ejecutivos.add(ejecutivo)   # M2M es la fuente de verdad; el escalar queda como fallback
        perfiles_actualizados += 1

    return {
      "creados": creados,
      "actualizados": actualizados,
      "marcados_inactivos": marcados_inactivos,
      "perfiles_actualizados": perfiles_actualizados,
    }
