from django.test import TestCase
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos import services
from pedidosRechazados.models import PedidoRechazado
from envios.models import EnvioCourier
from utils import Courier
from .factories import crear_usuario, crear_ejecutivo, crear_pedido

Rol = PerfilUsuario.Rol


class RechazarPedidoTest(TestCase):
    def setUp(self):
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        self.ejec_user = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)

    def test_rechazar_admin_archiva_y_borra(self):
        p = crear_pedido(num="5000")
        pk = p.pk
        services.rechazar_pedido(p, "cliente canceló", self.admin)
        self.assertFalse(Pedido.objects.filter(pk=pk).exists())              # sale de activos
        self.assertTrue(PedidoRechazado.objects.filter(num_pedido="5000").exists())  # queda archivado

    def test_rechazar_ajeno_a_otro_ejecutivo_falla(self):
        p = crear_pedido(num="5001", ejecutivo=self.ejec_obj)
        with self.assertRaises(PermissionError):
            services.rechazar_pedido(p, "x", self.ajeno)
        self.assertTrue(Pedido.objects.filter(pk=p.pk).exists())             # sigue vivo

    def test_dueno_puede_rechazar_su_propio_pedido(self):
        p = crear_pedido(num="5002", ejecutivo=self.ejec_obj)
        services.rechazar_pedido(p, "cliente canceló", self.ejec_user)
        self.assertFalse(Pedido.objects.filter(num_pedido="5002").exists())
        self.assertTrue(PedidoRechazado.objects.filter(num_pedido="5002").exists())

    def test_dueno_no_puede_rechazar_tras_despachar(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        p = crear_pedido(num="5003", ejecutivo=self.ejec_obj, envio=envio)
        with self.assertRaises(PermissionError):
            services.rechazar_pedido(p, "x", self.ejec_user)
        self.assertTrue(Pedido.objects.filter(pk=p.pk).exists())
