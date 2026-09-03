"""Vistas de seguimientoOnt/views.py: lista (scope + filtros), detalle, editar."""
import datetime
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.tests.factories import crear_usuario, crear_ejecutivo, crear_pedido
from .models import DespachoOnt

Rol = PerfilUsuario.Rol


class ListaOntViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_ont = crear_ejecutivo(codigo_sap=44, es_ont=True)
        self.ejec_ajeno = crear_ejecutivo(codigo_sap=99, es_ont=False)
        self.dueno = crear_usuario("dueno_ont_v@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=44)
        self.ajeno = crear_usuario("ajeno_ont_v@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        self.logi = crear_usuario("logi_ont_v@bioquimica.cl", Rol.LOGISTICA)

        pedido = crear_pedido("4001", ejecutivo=self.ejec_ont, nombre_contacto="Cliente Uno")
        self.seguimiento = DespachoOnt.objects.create(pedido=pedido, accion=DespachoOnt.Accion.GUIA_PEDIDA)

    def test_dueno_ve_el_suyo(self):
        self.client.force_login(self.dueno)
        resp = self.client.get("/ont/")
        self.assertContains(resp, "4001")

    def test_ajeno_no_ve_nada(self):
        self.client.force_login(self.ajeno)
        resp = self.client.get("/ont/")
        self.assertNotContains(resp, "4001")

    def test_logistica_ve_todo(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/ont/")
        self.assertContains(resp, "4001")

    def test_filtro_por_accion(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/ont/", {"accion": "ENTREGADO"})
        self.assertNotContains(resp, "4001")
        resp = self.client.get("/ont/", {"accion": "GUIA_PEDIDA"})
        self.assertContains(resp, "4001")

    def test_buscar_por_nombre_contacto(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/ont/", {"q": "Cliente Uno"})
        self.assertContains(resp, "4001")
        resp = self.client.get("/ont/", {"q": "Nadie Existe"})
        self.assertNotContains(resp, "4001")


class DetalleOntViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_ont = crear_ejecutivo(codigo_sap=44, es_ont=True)
        self.dueno = crear_usuario("dueno_ont_d@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=44)
        self.ajeno = crear_usuario("ajeno_ont_d@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        pedido = crear_pedido("4002", ejecutivo=self.ejec_ont)
        self.seguimiento = DespachoOnt.objects.create(pedido=pedido)

    def test_dueno_puede_ver(self):
        self.client.force_login(self.dueno)
        resp = self.client.get(f"/ont/{self.seguimiento.pk}/")
        self.assertEqual(resp.status_code, 200)

    def test_ajeno_es_redirigido(self):
        self.client.force_login(self.ajeno)
        resp = self.client.get(f"/ont/{self.seguimiento.pk}/")
        self.assertEqual(resp.status_code, 302)


class EditarOntViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_ont = crear_ejecutivo(codigo_sap=44, es_ont=True)
        self.dueno = crear_usuario("dueno_ont_e@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=44)
        self.ajeno = crear_usuario("ajeno_ont_e@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        pedido = crear_pedido("4003", ejecutivo=self.ejec_ont)
        self.seguimiento = DespachoOnt.objects.create(pedido=pedido)

    def test_dueno_puede_editar(self):
        self.client.force_login(self.dueno)
        resp = self.client.post(f"/ont/{self.seguimiento.pk}/editar/", {
            "accion": "GUIA_LISTA",
            "fecha_compromiso": "2026-09-15",
            "fecha_compromiso_aproximada": "on",
            "fecha_despacho": "2026-09-10",
            "guia_despacho": "11223344",
            "observaciones_ok": "Todo en orden",
            "observaciones_entrega": "Entregar en portería",
            "confirmacion_carga": "on",
            "confirmacion_cliente": "on",
            "retorno_documento": "on",
            "pedido_recibido": "on",
            "enviar": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.seguimiento.refresh_from_db()
        self.assertEqual(self.seguimiento.accion, "GUIA_LISTA")
        self.assertEqual(self.seguimiento.fecha_compromiso, datetime.date(2026, 9, 15))
        self.assertTrue(self.seguimiento.fecha_compromiso_aproximada)
        self.assertEqual(self.seguimiento.fecha_despacho, datetime.date(2026, 9, 10))
        self.assertEqual(self.seguimiento.guia_despacho, "11223344")
        self.assertEqual(self.seguimiento.observaciones_ok, "Todo en orden")
        self.assertTrue(self.seguimiento.confirmacion_cliente)
        self.assertTrue(self.seguimiento.retorno_documento)
        self.assertTrue(self.seguimiento.pedido_recibido)
        self.assertTrue(self.seguimiento.enviar)

    def test_dejar_un_checkbox_sin_marcar_lo_apaga(self):
        self.seguimiento.confirmacion_cliente = True
        self.seguimiento.save()
        self.client.force_login(self.dueno)
        self.client.post(f"/ont/{self.seguimiento.pk}/editar/", {"accion": ""})  # sin "confirmacion_cliente"
        self.seguimiento.refresh_from_db()
        self.assertFalse(self.seguimiento.confirmacion_cliente)

    def test_ajeno_no_puede_editar(self):
        self.client.force_login(self.ajeno)
        resp = self.client.post(f"/ont/{self.seguimiento.pk}/editar/", {"accion": "ENTREGADO"})
        self.assertEqual(resp.status_code, 403)
        self.seguimiento.refresh_from_db()
        self.assertEqual(self.seguimiento.accion, "")


class EditarCampoOntViewTest(TestCase):
    """editar_campo_ont: guarda UN campo a la vez (celda de la tabla tipo planilla) sin pisar el
    resto — a diferencia de editar_ont, que asume que siempre llega el form completo."""

    def setUp(self):
        self.client = Client()
        self.ejec_ont = crear_ejecutivo(codigo_sap=44, es_ont=True)
        self.dueno = crear_usuario("dueno_ont_c@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=44)
        self.ajeno = crear_usuario("ajeno_ont_c@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        pedido = crear_pedido("4004", ejecutivo=self.ejec_ont)
        self.seguimiento = DespachoOnt.objects.create(
            pedido=pedido, accion=DespachoOnt.Accion.GUIA_PEDIDA, guia_despacho="OLD-1", confirmacion_cliente=True,
        )

    def _post(self, campo, valor=None):
        data = {} if valor is None else {"valor": valor}
        return self.client.post(f"/ont/{self.seguimiento.pk}/campo/{campo}/", data)

    def test_edita_texto_sin_tocar_los_demas_campos(self):
        self.client.force_login(self.dueno)
        resp = self._post("guia_despacho", "NUEVA-99")
        self.assertEqual(resp.status_code, 204)
        self.seguimiento.refresh_from_db()
        self.assertEqual(self.seguimiento.guia_despacho, "NUEVA-99")
        self.assertEqual(self.seguimiento.accion, DespachoOnt.Accion.GUIA_PEDIDA)  # no se pisó
        self.assertTrue(self.seguimiento.confirmacion_cliente)                     # no se pisó

    def test_marca_checkbox(self):
        self.client.force_login(self.dueno)
        resp = self._post("pedido_recibido", "on")
        self.assertEqual(resp.status_code, 204)
        self.seguimiento.refresh_from_db()
        self.assertTrue(self.seguimiento.pedido_recibido)

    def test_desmarcar_checkbox_no_manda_valor_y_lo_apaga(self):
        self.client.force_login(self.dueno)
        resp = self._post("confirmacion_cliente")  # checkbox destildado: el navegador no manda "valor"
        self.assertEqual(resp.status_code, 204)
        self.seguimiento.refresh_from_db()
        self.assertFalse(self.seguimiento.confirmacion_cliente)

    def test_fecha_vacia_la_limpia(self):
        self.seguimiento.fecha_compromiso = datetime.date(2026, 1, 1)
        self.seguimiento.save()
        self.client.force_login(self.dueno)
        resp = self._post("fecha_compromiso")
        self.assertEqual(resp.status_code, 204)
        self.seguimiento.refresh_from_db()
        self.assertIsNone(self.seguimiento.fecha_compromiso)

    def test_accion_invalida_da_400(self):
        self.client.force_login(self.dueno)
        resp = self._post("accion", "NO_EXISTE")
        self.assertEqual(resp.status_code, 400)
        self.seguimiento.refresh_from_db()
        self.assertEqual(self.seguimiento.accion, DespachoOnt.Accion.GUIA_PEDIDA)  # no se tocó

    def test_campo_fuera_de_la_whitelist_da_404(self):
        self.client.force_login(self.dueno)
        resp = self._post("pedido_id", "1")
        self.assertEqual(resp.status_code, 404)

    def test_ajeno_no_puede_editar_campo(self):
        self.client.force_login(self.ajeno)
        resp = self._post("guia_despacho", "HACKEO")
        self.assertEqual(resp.status_code, 403)
        self.seguimiento.refresh_from_db()
        self.assertEqual(self.seguimiento.guia_despacho, "OLD-1")
