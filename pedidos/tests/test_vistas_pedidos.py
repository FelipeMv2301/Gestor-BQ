"""Vistas de acción sobre un pedido individual (pedidos/views/pedidos.py) — request real vía Client."""
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from envios.models import EnvioCourier
from utils import Courier
from .factories import crear_usuario, crear_ejecutivo, crear_pedido

Rol = PerfilUsuario.Rol


class DuplicarVistaTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        self.pedido = crear_pedido(
            num="2601820", envio=self.envio, courier=Courier.CHIBRA,
            estado_comercial=Pedido.EstadoComercial.APROBADO,
            ejecutivo=self.ejec_obj,  # visible para self.ejec (mismo código SAP), pero no puede duplicar
        )
        self.sin_envio = crear_pedido(num="3000001", courier=Courier.CHIBRA)

    def test_get_muestra_modal_de_confirmacion(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/{self.pedido.pk}/duplicar/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Duplicar pedido", resp.content.decode())

    def test_post_duplica_y_redirige(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/{self.pedido.pk}/duplicar/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp["HX-Redirect"], "/pedidos/mis-pedidos/")
        self.assertTrue(Pedido.objects.filter(num_pedido="2601820-2").exists())

    def test_ejecutivo_no_puede_duplicar(self):
        self.client.force_login(self.ejec)
        resp = self.client.get(f"/pedidos/{self.pedido.pk}/duplicar/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp["HX-Trigger"], '{"toast": {"level": "error", "body": "No puedes duplicar este pedido."}}')

    def test_pedido_sin_envio_tambien_se_puede_duplicar(self):
        # Sin restricción por estado de envío — Logística decide cuándo corresponde.
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/{self.sin_envio.pk}/duplicar/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp["HX-Redirect"], "/pedidos/mis-pedidos/")
        self.assertTrue(Pedido.objects.filter(num_pedido="3000001-2").exists())
