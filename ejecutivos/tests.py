"""ejecutivos/services.py::sincronizar_ejecutivos_desde_sap — mockea SAP en la frontera, nunca red real."""
from unittest.mock import patch
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from .models import Ejecutivo
from .services import sincronizar_ejecutivos_desde_sap
from pedidos.tests.factories import crear_usuario


def _sap_person(codigo, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True):
    return {"SalesEmployeeCode": codigo, "SalesEmployeeName": nombre, "Email": email,
            "Active": "tYES" if activo else "tNO"}


def _mockear(datos_sap):
    return (
        patch("ejecutivos.services.obtener_cookies_sap", return_value={}),
        patch("ejecutivos.services.obtener_todas_las_paginas", return_value=datos_sap),
    )


class SincronizarEjecutivosTest(TestCase):
    def test_crea_ejecutivos_nuevos(self):
        m1, m2 = _mockear([_sap_person(10), _sap_person(20, nombre="Pedro Soto", email="pedro@bioquimica.cl")])
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado["creados"], 2)
        self.assertEqual(resultado["actualizados"], 0)
        self.assertTrue(Ejecutivo.objects.filter(codigo_sap=10, nombre="Elsa Martínez").exists())

    def test_actualiza_ejecutivo_existente(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Nombre Viejo", email="viejo@bioquimica.cl")
        m1, m2 = _mockear([_sap_person(10, nombre="Nombre Nuevo", email="nuevo@bioquimica.cl")])
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado, {"creados": 0, "actualizados": 1, "marcados_inactivos": 0, "perfiles_actualizados": 0})
        ejecutivo = Ejecutivo.objects.get(codigo_sap=10)
        self.assertEqual(ejecutivo.nombre, "Nombre Nuevo")
        self.assertEqual(ejecutivo.email, "nuevo@bioquimica.cl")

    def test_codigo_negativo_se_ignora(self):
        m1, m2 = _mockear([_sap_person(-1)])
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado["creados"], 0)
        self.assertEqual(Ejecutivo.objects.count(), 0)

    def test_marca_inactivo_al_que_ya_no_viene_de_sap(self):
        Ejecutivo.objects.create(codigo_sap=99, nombre="Ya no está", email="x@bioquimica.cl", activo=True)
        m1, m2 = _mockear([_sap_person(10)])  # el 99 no aparece más
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado["marcados_inactivos"], 1)
        self.assertFalse(Ejecutivo.objects.get(codigo_sap=99).activo)

    def test_activo_false_en_sap_no_lo_marca_como_creado_activo(self):
        m1, m2 = _mockear([_sap_person(10, activo=False)])
        with m1, m2:
            sincronizar_ejecutivos_desde_sap()
        self.assertFalse(Ejecutivo.objects.get(codigo_sap=10).activo)

    def test_vincula_perfil_sin_codigo_por_email(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True)
        usuario = crear_usuario("elsa@bioquimica.cl")  # PerfilUsuario se crea solo, sin codigo_empleado_sap
        # el código 10 tiene que venir en esta corrida, si no "marcar inactivos" lo apaga antes de vincular
        m1, m2 = _mockear([_sap_person(10)])
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado["perfiles_actualizados"], 1)
        usuario.perfil.refresh_from_db()
        self.assertEqual(usuario.perfil.codigo_empleado_sap, 10)

    def test_vincula_por_m2m_aunque_el_escalar_ya_lo_tenga_otro_perfil(self):
        """Varios perfiles pueden compartir el mismo código SAP (decisión de Felipe 2026-09-02):
        el escalar sigue siendo 1:1 (unique en DB) y no se pisa, pero la M2M sí vincula al segundo."""
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True)
        ya_vinculado = crear_usuario("otra@bioquimica.cl", codigo_sap=10)
        sin_vincular = crear_usuario("elsa@bioquimica.cl")
        m1, m2 = _mockear([_sap_person(10)])
        with m1, m2:
            resultado = sincronizar_ejecutivos_desde_sap()
        self.assertEqual(resultado["perfiles_actualizados"], 1)
        sin_vincular.perfil.refresh_from_db()
        self.assertIsNone(sin_vincular.perfil.codigo_empleado_sap)  # escalar sigue 1:1, no se pisa
        self.assertEqual(sin_vincular.perfil.codigos_sap, [10])     # pero la M2M sí lo vincula


#El rol ADMIN del portal (login Google) nunca entra al /admin/ real de Django — antes es_ont solo era
#editable ahí (list_editable en EjecutivoAdmin), así que en la práctica nadie podía marcarlo. Este es
#el panel que sí usa el ADMIN del portal (ejecutivos:panel/editar) — ver backlog-seguimiento-ont.md.
class PanelEjecutivosEsOntTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin_panel_ejec@bioquimica.cl", PerfilUsuario.Rol.ADMIN)
        self.ejecutivo = Ejecutivo.objects.create(codigo_sap=44, nombre="Ejecutivo ONT", es_ont=False)

    def test_admin_puede_marcar_es_ont_desde_el_panel_propio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/ejecutivos/panel/{self.ejecutivo.pk}/editar/", {
            "codigo_sap": "44", "nombre": "Ejecutivo ONT", "email": "", "activo": "on", "es_ont": "on",
        })
        self.assertEqual(resp.status_code, 204)
        self.ejecutivo.refresh_from_db()
        self.assertTrue(self.ejecutivo.es_ont)

    def test_panel_muestra_la_columna_ont(self):
        self.client.force_login(self.admin)
        resp = self.client.get("/ejecutivos/panel/")
        self.assertContains(resp, "ONT")
