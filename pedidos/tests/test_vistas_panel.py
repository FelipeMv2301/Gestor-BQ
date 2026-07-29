"""Panel Admin (pedidos/views/panel.py): CRUD de SkuCourier + sincronizar/cargar individual (mockeados)."""
from unittest.mock import patch
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.models import SkuCourier
from utils import Courier
from .factories import crear_usuario

Rol = PerfilUsuario.Rol


class PanelSkusPermisosTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_no_admin_no_ve_el_panel(self):
        self.client.force_login(self.ejec)
        resp = self.client.get("/pedidos/panel/skus/")
        self.assertEqual(resp.status_code, 302)

    def test_admin_ve_el_panel(self):
        SkuCourier.objects.create(sku="ABC123", courier=Courier.CHIBRA)
        self.client.force_login(self.admin)
        resp = self.client.get("/pedidos/panel/skus/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ABC123")


class CrearSkuTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_no_admin_no_puede_crear(self):
        self.client.force_login(self.ejec)
        self.client.post("/pedidos/panel/skus/crear/", {"sku": "XYZ999", "courier": Courier.CHIBRA})
        self.assertFalse(SkuCourier.objects.filter(sku="XYZ999").exists())

    def test_admin_crea_sku(self):
        self.client.force_login(self.admin)
        resp = self.client.post("/pedidos/panel/skus/crear/",
                                 {"sku": "xyz999", "courier": Courier.CHIBRA, "servicio_codigo": "", "servicio_nombre": ""})
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(SkuCourier.objects.filter(sku="XYZ999").exists())  # normalizado a mayúsculas

    def test_admin_datos_invalidos_no_crea(self):
        self.client.force_login(self.admin)
        self.client.post("/pedidos/panel/skus/crear/", {"sku": "", "courier": Courier.CHIBRA})
        self.assertEqual(SkuCourier.objects.count(), 0)


class EditarSkuTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.sku = SkuCourier.objects.create(sku="ABC123", courier=Courier.CHIBRA)

    def test_admin_edita_servicio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/pedidos/panel/skus/{self.sku.pk}/editar/",
                                 {"sku": "ABC123", "courier": Courier.CHIBRA,
                                  "servicio_codigo": "10", "servicio_nombre": "Express"})
        self.assertEqual(resp.status_code, 204)
        self.sku.refresh_from_db()
        self.assertEqual(self.sku.servicio_codigo, "10")
        self.assertEqual(self.sku.servicio_nombre, "Express")


class EliminarSkuTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.sku = SkuCourier.objects.create(sku="ABC123", courier=Courier.CHIBRA)

    def test_no_admin_no_puede_eliminar(self):
        self.client.force_login(self.ejec)
        self.client.post(f"/pedidos/panel/skus/{self.sku.pk}/eliminar/")
        self.assertTrue(SkuCourier.objects.filter(pk=self.sku.pk).exists())

    def test_admin_elimina(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/pedidos/panel/skus/{self.sku.pk}/eliminar/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SkuCourier.objects.filter(pk=self.sku.pk).exists())


class SincronizarYCargarIndividualTest(TestCase):
    """Solo gating + delegación — guardar_pedidos_sap/woo ya están probados a fondo aparte."""

    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)

    def test_sincronizar_delega_en_sap_y_woo(self):
        self.client.force_login(self.admin)
        with patch("pedidos.views.panel.services.guardar_pedidos_sap", return_value={"creados": 1, "omitidos": 0}) as m_sap, \
             patch("pedidos.views.panel.services.guardar_pedidos_woo", return_value={"creados": 2, "omitidos": 0}) as m_woo:
            resp = self.client.post("/pedidos/panel/sincronizar/", {"after": "2026-01-01", "before": "2026-01-02"})
        self.assertEqual(resp.status_code, 204)
        m_sap.assert_called_once_with(after="2026-01-01", before="2026-01-02")
        m_woo.assert_called_once_with(after="2026-01-01T00:00:00", before="2026-01-02T23:59:59")

    def test_sincronizar_sin_fecha_desde_no_llama_nada(self):
        self.client.force_login(self.admin)
        with patch("pedidos.views.panel.services.guardar_pedidos_sap") as m_sap:
            self.client.post("/pedidos/panel/sincronizar/", {})
        m_sap.assert_not_called()

    def test_cargar_individual_sap(self):
        self.client.force_login(self.admin)
        with patch("pedidos.views.panel.services.guardar_un_pedido_sap", return_value="ok") as m:
            self.client.post("/pedidos/panel/cargar/", {"num_pedido": "123", "origen": "SAP"})
        m.assert_called_once_with("123")

    def test_cargar_individual_origen_invalido(self):
        self.client.force_login(self.admin)
        resp = self.client.post("/pedidos/panel/cargar/", {"num_pedido": "123", "origen": "FTP"})
        self.assertEqual(resp.status_code, 204)  # no rompe, solo reporta error por messages
