"""Render de pedidos/views/despacho.py::armar_despacho — nadie lo probaba por courier hasta ahora.
assertContains ya falla si el template tira 500 (typo de {% %}, variable mal armada, etc.)."""
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from utils import Courier
from .factories import crear_usuario, crear_pedido

Rol = PerfilUsuario.Rol


class ArmarDespachoTemplateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)

    def _pedido_aprobado(self, num, courier):
        return crear_pedido(
            num, estado_comercial=Pedido.EstadoComercial.APROBADO, courier=courier, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_render_starken(self):
        p = self._pedido_aprobado("7001", Courier.STARKEN)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "starken_calle")
        self.assertContains(resp, "codigo_agencia_destino")
        self.assertContains(resp, "doc_tipo")
        self.assertContains(resp, 'name="bulto_tipo" value="CAJA"')

    def test_render_chibra_sigue_funcionando(self):
        p = self._pedido_aprobado("7002", Courier.CHIBRA)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "destinatario_direccion")

    def test_render_moveup_sigue_funcionando(self):
        p = self._pedido_aprobado("7003", Courier.MOVEUP)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "moveup_calle")
