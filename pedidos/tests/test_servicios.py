from django.test import TestCase
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos import services
from utils import Courier
from pedidosRechazados.models import PedidoRechazado
from .factories import crear_usuario, crear_ejecutivo, crear_pedido

Rol = PerfilUsuario.Rol
EC = Pedido.EstadoComercial


class AprobarPedidoTest(TestCase):
    def setUp(self):
        self.ejec = crear_ejecutivo(codigo_sap=10)
        self.dueno = crear_usuario("dueno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)

    def _pedido_valido(self):
        return crear_pedido(
            ejecutivo=self.ejec, estado_comercial=EC.PENDIENTE, courier=Courier.CHIBRA,
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123",
            direccion_comuna="Providencia",
        )

    def test_aprobar_ok(self):
        p = self._pedido_valido()
        services.aprobar_pedido(p, self.dueno)
        p.refresh_from_db()
        self.assertEqual(p.estado_comercial, EC.APROBADO)

    def test_aprobar_no_dueno_falla(self):
        with self.assertRaises(PermissionError):
            services.aprobar_pedido(self._pedido_valido(), self.ajeno)

    def test_aprobar_sin_courier_falla(self):
        p = self._pedido_valido()
        p.courier = ""
        with self.assertRaises(ValueError):
            services.aprobar_pedido(p, self.dueno)

    def test_aprobar_sin_contacto_ni_direccion_falla(self):
        p = crear_pedido(ejecutivo=self.ejec, courier=Courier.CHIBRA)
        with self.assertRaises(ValueError):
            services.aprobar_pedido(p, self.dueno)

    def test_aprobar_estado_no_pendiente_falla(self):
        p = self._pedido_valido()
        p.estado_comercial = EC.APROBADO
        p.save()
        with self.assertRaises(ValueError):
            services.aprobar_pedido(p, self.dueno)


class RechazarPedidoTest(TestCase):
    def setUp(self):
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec_user = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_rechazar_admin_archiva_y_borra(self):
        p = crear_pedido(num="5000")
        pk = p.pk
        services.rechazar_pedido(p, "cliente canceló", self.admin)
        self.assertFalse(Pedido.objects.filter(pk=pk).exists())              # sale de activos
        self.assertTrue(PedidoRechazado.objects.filter(num_pedido="5000").exists())  # queda archivado

    def test_rechazar_no_admin_falla(self):
        p = crear_pedido(num="5001")
        with self.assertRaises(PermissionError):
            services.rechazar_pedido(p, "x", self.ejec_user)
        self.assertTrue(Pedido.objects.filter(pk=p.pk).exists())             # sigue vivo
