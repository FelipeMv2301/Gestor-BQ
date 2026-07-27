from django.test import TestCase
from pedidos.models import Pedido
from envios.models import EnvioCourier
from .factories import crear_pedido
from utils import Courier

EC = Pedido.EstadoComercial
EN = Pedido.EstadoNotificacion
TE = Pedido.TipoEntrega


class EstadoSeguimientoTest(TestCase):
    def test_pendiente(self):
        p = crear_pedido(estado_comercial=EC.PENDIENTE)
        self.assertEqual(p.estado_seguimiento, ("Pendiente de carga", "pend"))

    def test_retiro_sin_notificar(self):
        p = crear_pedido(estado_comercial=EC.APROBADO, tipo_entrega=TE.RETIRO_BIOQUIMICA)
        self.assertEqual(p.estado_seguimiento[1], "apro")
        self.assertIn("retiro", p.estado_seguimiento[0].lower())

    def test_retiro_notificado(self):
        p = crear_pedido(estado_comercial=EC.APROBADO, tipo_entrega=TE.RETIRO_BIOQUIMICA,
                         estado_notificacion=EN.NOTIFICADO)
        self.assertEqual(p.estado_seguimiento[1], "noti")

    def test_despacho_por_despachar(self):
        p = crear_pedido(estado_comercial=EC.APROBADO, tipo_entrega=TE.DESPACHO)
        self.assertEqual(p.estado_seguimiento, ("Por despachar", "apro"))

    def test_despacho_con_envio(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA,
                                            estado=EnvioCourier.Estado.DESPACHADO, orden_transporte="X-1")
        p = crear_pedido(estado_comercial=EC.APROBADO, tipo_entrega=TE.DESPACHO, envio=envio)
        self.assertEqual(p.estado_seguimiento[1], "apro")   # despachado, aún sin notificar

    def test_despacho_notificado(self):
        p = crear_pedido(estado_comercial=EC.APROBADO, tipo_entrega=TE.DESPACHO,
                         estado_notificacion=EN.NOTIFICADO)
        self.assertEqual(p.estado_seguimiento[1], "noti")


class PedidoQuerySetTest(TestCase):
    def setUp(self):
        self.sap = crear_pedido(num="2600", origen=Pedido.Origen.SAP, razon_social="Laboratorio Andes",
                                estado_comercial=EC.PENDIENTE, tipo_entrega=TE.DESPACHO, courier=Courier.CHIBRA)
        self.web = crear_pedido(num="18432", origen=Pedido.Origen.WEB, nombre_contacto="Juan Pérez",
                                estado_comercial=EC.APROBADO, tipo_entrega=TE.RETIRO_BIOQUIMICA,
                                estado_notificacion=EN.NOTIFICADO)

    def test_buscar_por_numero(self):
        self.assertEqual(Pedido.objects.buscar("2600").count(), 1)

    def test_buscar_por_cliente(self):
        self.assertEqual(Pedido.objects.buscar("andes").count(), 1)   # icontains

    def test_buscar_vacio_devuelve_todo(self):
        self.assertEqual(Pedido.objects.buscar("").count(), 2)

    def test_con_estado_comercial(self):
        self.assertEqual(Pedido.objects.con_estado_comercial(EC.APROBADO).count(), 1)
        self.assertEqual(Pedido.objects.con_estado_comercial(None).count(), 2)  # None = sin filtro

    def test_con_notificacion(self):
        self.assertEqual(Pedido.objects.con_notificacion([EN.NOTIFICADO]).count(), 1)
        self.assertEqual(Pedido.objects.con_notificacion([]).count(), 2)

    def test_con_courier(self):
        self.assertEqual(Pedido.objects.con_courier(["CHIBRA"]).count(), 1)
        # TODO: sumar caso MOVEUP cuando se reactive en utils.Courier

    def test_con_origen(self):
        self.assertEqual(Pedido.objects.con_origen(["WEB"]).count(), 1)

    def test_con_tipo_entrega(self):
        self.assertEqual(Pedido.objects.con_tipo_entrega([TE.RETIRO_BIOQUIMICA]).count(), 1)

    def test_con_envio(self):
        self.assertEqual(Pedido.objects.con_envio(["sin"]).count(), 2)      # ninguno tiene envío
        self.assertEqual(Pedido.objects.con_envio(["enviado"]).count(), 0)
        self.assertEqual(Pedido.objects.con_envio(["sin", "enviado"]).count(), 2)  # ambos = sin filtro

    def test_encadenado(self):
        # WEB + APROBADO + notificado → solo el web
        qs = Pedido.objects.con_origen(["WEB"]).con_estado_comercial(EC.APROBADO).con_notificacion([EN.NOTIFICADO])
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), self.web)
