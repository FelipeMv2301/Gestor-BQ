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


class DuplicarPedidoTest(TestCase):
    def setUp(self):
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec_user = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        self.original = crear_pedido(
            num="2601820", envio=self.envio, courier=Courier.CHIBRA,
            estado_comercial=Pedido.EstadoComercial.APROBADO,
            estado_notificacion=Pedido.EstadoNotificacion.NOTIFICADO,
            rut="76563320-6", razon_social="Bioquimica CL",
            direccion_calle="Calle 1", direccion_comuna="Santiago",
        )

    def test_primera_copia_sale_con_sufijo_2(self):
        copia = services.duplicar_pedido(self.original, self.logi)
        self.assertEqual(copia.num_pedido, "2601820-2")
        self.assertIsNone(copia.envio_id)
        self.assertEqual(copia.estado_notificacion, Pedido.EstadoNotificacion.NO_NOTIFICADO)
        self.assertEqual(copia.estado_comercial, Pedido.EstadoComercial.APROBADO)

    def test_copia_hereda_datos_de_destinatario_y_courier(self):
        copia = services.duplicar_pedido(self.original, self.logi)
        self.assertEqual(copia.rut, self.original.rut)
        self.assertEqual(copia.razon_social, self.original.razon_social)
        self.assertEqual(copia.direccion_calle, self.original.direccion_calle)
        self.assertEqual(copia.courier, self.original.courier)
        self.assertEqual(copia.origen, self.original.origen)

    def test_original_no_se_modifica(self):
        services.duplicar_pedido(self.original, self.logi)
        self.original.refresh_from_db()
        self.assertEqual(self.original.num_pedido, "2601820")
        self.assertEqual(self.original.envio_id, self.envio.id)
        self.assertEqual(self.original.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)

    def test_segunda_duplicacion_sale_con_sufijo_3(self):
        services.duplicar_pedido(self.original, self.logi)
        copia2 = services.duplicar_pedido(self.original, self.logi)
        self.assertEqual(copia2.num_pedido, "2601820-3")

    def test_duplicar_una_copia_ya_despachada_no_encadena_sufijo(self):
        copia = services.duplicar_pedido(self.original, self.logi)
        copia.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        copia.save(update_fields=["envio"])
        copia2 = services.duplicar_pedido(copia, self.logi)
        self.assertEqual(copia2.num_pedido, "2601820-3")  # no "2601820-2-2"

    def test_ejecutivo_no_puede_duplicar(self):
        with self.assertRaises(PermissionError):
            services.duplicar_pedido(self.original, self.ejec_user)
        self.assertEqual(Pedido.objects.filter(origen="SAP", num_pedido="2601820-2").count(), 0)

    def test_pedido_sin_envio_tambien_se_puede_duplicar(self):
        # Sin restricción por estado de envío — Logística decide cuándo corresponde.
        sin_envio = crear_pedido(num="3000001", courier=Courier.CHIBRA)
        copia = services.duplicar_pedido(sin_envio, self.logi)
        self.assertEqual(copia.num_pedido, "3000001-2")
