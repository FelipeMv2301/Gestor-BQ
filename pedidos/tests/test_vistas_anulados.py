"""Vistas de Anulados (pedidos/views/pedidos.py): listado, reingresar, editar motivo, eliminar permanente."""
from unittest.mock import patch
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidosRechazados.models import PedidoRechazado
from .factories import crear_usuario, crear_ejecutivo

Rol = PerfilUsuario.Rol


class AnuladosListadoTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        #Ejecutivo real de nadie en este test (ni dueno ni ajeno lo tienen vinculado) — usar su pk real
        #en vez de un entero mágico tipo "999": un pk hardcodeado puede coincidir por casualidad con un
        #Ejecutivo real creado por OTRO test de la suite completa (el autoincrement no se resetea entre
        #TestCase), lo que hacía este test frágil y dependiente del orden/tamaño total de la suite.
        self.ejec_ajeno = crear_ejecutivo(codigo_sap=30, nombre="Nadie lo tiene", email="nadie_dueno@bioquimica.cl")
        self.dueno = crear_usuario("dueno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        PedidoRechazado.objects.create(origen="SAP", num_pedido="1", motivo="m1", snapshot={"ejecutivo": self.ejec_obj.pk})
        PedidoRechazado.objects.create(origen="SAP", num_pedido="2", motivo="m2", snapshot={"ejecutivo": self.ejec_ajeno.pk})

    def test_admin_ve_todos(self):
        self.client.force_login(self.admin)
        resp = self.client.get("/pedidos/anulados/")
        self.assertContains(resp, "m1")
        self.assertContains(resp, "m2")

    def test_ejecutivo_solo_ve_los_suyos(self):
        self.client.force_login(self.dueno)
        resp = self.client.get("/pedidos/anulados/")
        self.assertContains(resp, "m1")
        self.assertNotContains(resp, "m2")

    def test_ajeno_no_ve_nada(self):
        self.client.force_login(self.ajeno)
        resp = self.client.get("/pedidos/anulados/")
        self.assertNotContains(resp, "m1")
        self.assertNotContains(resp, "m2")


class ReingresarViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        self.dueno = crear_usuario("dueno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)
        self.rechazado = PedidoRechazado.objects.create(
            origen="SAP", num_pedido="7500", snapshot={"ejecutivo": self.ejec_obj.pk})

    def test_dueno_puede_reingresar(self):
        self.client.force_login(self.dueno)
        with patch("pedidos.views.pedidos.services.reingresar_pedido", return_value="ok") as mock_reingresar:
            resp = self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/reingresar/")
        self.assertEqual(resp.status_code, 204)
        mock_reingresar.assert_called_once_with(self.rechazado)

    def test_ajeno_no_puede_reingresar(self):
        self.client.force_login(self.ajeno)
        with patch("pedidos.views.pedidos.services.reingresar_pedido") as mock_reingresar:
            self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/reingresar/")
        mock_reingresar.assert_not_called()
        self.assertTrue(PedidoRechazado.objects.filter(pk=self.rechazado.pk).exists())


class EditarMotivoRechazadoTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.rechazado = PedidoRechazado.objects.create(origen="SAP", num_pedido="8500", motivo="viejo", snapshot={})

    def test_no_admin_no_puede_editar(self):
        self.client.force_login(self.ejec)
        self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/motivo/", {"motivo": "nuevo"})
        self.rechazado.refresh_from_db()
        self.assertEqual(self.rechazado.motivo, "viejo")

    def test_admin_edita_motivo(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/motivo/", {"motivo": "corregido"})
        self.assertEqual(resp.status_code, 204)
        self.rechazado.refresh_from_db()
        self.assertEqual(self.rechazado.motivo, "corregido")


class EliminarRechazadoTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.rechazado = PedidoRechazado.objects.create(origen="SAP", num_pedido="8501", snapshot={})

    def test_no_admin_no_puede_eliminar(self):
        self.client.force_login(self.ejec)
        self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/eliminar/")
        self.assertTrue(PedidoRechazado.objects.filter(pk=self.rechazado.pk).exists())

    def test_admin_elimina_permanente(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/pedidos/anulados/{self.rechazado.pk}/eliminar/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(PedidoRechazado.objects.filter(pk=self.rechazado.pk).exists())
