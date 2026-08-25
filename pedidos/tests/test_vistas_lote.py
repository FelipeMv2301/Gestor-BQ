"""Vistas de acción sobre selección múltiple (pedidos/views/lote.py) — request real vía Client."""
import smtplib
from unittest.mock import patch
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from utils import Courier
from pedidosRechazados.models import PedidoRechazado
from envios.models import EnvioCourier
from .factories import crear_usuario, crear_ejecutivo, crear_pedido

Rol = PerfilUsuario.Rol
EC = Pedido.EstadoComercial


class EliminarLoteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_no_admin_no_elimina(self):
        p = crear_pedido("3001")
        self.client.force_login(self.ejec)
        self.client.post("/pedidos/lote/eliminar/", {"ids": [p.pk]})
        self.assertTrue(Pedido.objects.filter(pk=p.pk).exists())

    def test_admin_elimina_los_seleccionados(self):
        p1 = crear_pedido("3002")
        p2 = crear_pedido("3003")
        p3 = crear_pedido("3004")  # no seleccionado, debe sobrevivir
        self.client.force_login(self.admin)
        resp = self.client.post("/pedidos/lote/eliminar/", {"ids": [p1.pk, p2.pk]})
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Pedido.objects.filter(pk__in=[p1.pk, p2.pk]).exists())
        self.assertTrue(Pedido.objects.filter(pk=p3.pk).exists())

    def test_sin_seleccion_no_hace_nada(self):
        crear_pedido("3005")
        self.client.force_login(self.admin)
        resp = self.client.post("/pedidos/lote/eliminar/", {"ids": []})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Pedido.objects.count(), 1)


class RechazarLoteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        self.dueno = crear_usuario("dueno_rl@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno_rl@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)

    def test_dueno_anula_los_seleccionados_sin_despachar(self):
        p1 = crear_pedido("6001", ejecutivo=self.ejec_obj)
        p2 = crear_pedido("6002", ejecutivo=self.ejec_obj)

        self.client.force_login(self.dueno)
        resp = self.client.post("/pedidos/lote/rechazar/", {"ids": [p1.pk, p2.pk]})

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Pedido.objects.filter(pk__in=[p1.pk, p2.pk]).exists())
        self.assertEqual(PedidoRechazado.objects.filter(num_pedido__in=["6001", "6002"]).count(), 2)

    def test_ya_despachado_no_se_anula_pero_no_bloquea_al_resto(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        despachado = crear_pedido("6003", ejecutivo=self.ejec_obj, envio=envio)
        sin_despachar = crear_pedido("6004", ejecutivo=self.ejec_obj)

        self.client.force_login(self.dueno)
        self.client.post("/pedidos/lote/rechazar/", {"ids": [despachado.pk, sin_despachar.pk]})

        self.assertTrue(Pedido.objects.filter(pk=despachado.pk).exists())  # no se pudo anular
        self.assertFalse(Pedido.objects.filter(pk=sin_despachar.pk).exists())  # este sí

    def test_ajeno_no_puede_anular_pedido_de_otro_ejecutivo(self):
        # queryset_para_ver ya scoping por dueño — el ajeno ni ve este pedido en su queryset
        p = crear_pedido("6005", ejecutivo=self.ejec_obj)
        self.client.force_login(self.ajeno)
        self.client.post("/pedidos/lote/rechazar/", {"ids": [p.pk]})
        self.assertTrue(Pedido.objects.filter(pk=p.pk).exists())


class NotificarLoteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)

    def _pedido_aprobado(self, num):
        return crear_pedido(num, estado_comercial=EC.APROBADO, courier=Courier.CHIBRA)

    def test_notifica_los_aprobados(self):
        p1 = self._pedido_aprobado("4101")
        p2 = self._pedido_aprobado("4102")

        self.client.force_login(self.logi)
        with patch("pedidos.services.email_client.enviar_notificacion") as mock_email:
            resp = self.client.post("/pedidos/lote/notificar/", {"ids": [p1.pk, p2.pk]})

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(mock_email.call_count, 2)
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)
        self.assertEqual(p2.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)

    def test_ya_notificado_no_se_reenvia_pero_no_rompe_el_lote(self):
        ya_notificado = self._pedido_aprobado("4103")
        ya_notificado.estado_notificacion = Pedido.EstadoNotificacion.NOTIFICADO
        ya_notificado.save()
        pendiente = self._pedido_aprobado("4104")

        self.client.force_login(self.logi)
        with patch("pedidos.services.email_client.enviar_notificacion") as mock_email:
            self.client.post("/pedidos/lote/notificar/", {"ids": [ya_notificado.pk, pendiente.pk]})

        self.assertEqual(mock_email.call_count, 1)  # solo el pendiente
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)

    def test_error_smtp_real_no_bloquea_al_resto_del_lote(self):
        # Antes del fix: un error que no fuera ValueError (ej. SMTP caído) cortaba el loop
        # y los pedidos siguientes del mismo lote ni se intentaban notificar.
        p1 = self._pedido_aprobado("4105")
        p2 = self._pedido_aprobado("4106")
        p3 = self._pedido_aprobado("4107")

        self.client.force_login(self.logi)
        with patch("pedidos.services.email_client.enviar_notificacion",
                   side_effect=[smtplib.SMTPConnectError(421, "caído"), None, None]):
            self.client.post("/pedidos/lote/notificar/", {"ids": [p1.pk, p2.pk, p3.pk]})

        p1.refresh_from_db(); p2.refresh_from_db(); p3.refresh_from_db()
        self.assertEqual(p1.estado_notificacion, Pedido.EstadoNotificacion.NO_NOTIFICADO)  # el que falló
        self.assertEqual(p2.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)      # no se salta
        self.assertEqual(p3.estado_notificacion, Pedido.EstadoNotificacion.NOTIFICADO)


class DuplicarLoteTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_duplica_los_seleccionados_sin_restriccion_de_envio(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        con_envio = crear_pedido("7001", envio=envio, courier=Courier.CHIBRA)
        sin_envio = crear_pedido("7002", courier=Courier.CHIBRA)

        self.client.force_login(self.logi)
        resp = self.client.post("/pedidos/lote/duplicar/", {"ids": [con_envio.pk, sin_envio.pk]})

        self.assertEqual(resp.status_code, 204)
        self.assertTrue(Pedido.objects.filter(num_pedido="7001-2").exists())
        self.assertTrue(Pedido.objects.filter(num_pedido="7002-2").exists())

    def test_ejecutivo_no_puede_duplicar_por_lote(self):
        p = crear_pedido("7003", courier=Courier.CHIBRA)
        self.client.force_login(self.ejec)
        self.client.post("/pedidos/lote/duplicar/", {"ids": [p.pk]})
        self.assertFalse(Pedido.objects.filter(num_pedido="7003-2").exists())

    def test_sin_seleccion_no_hace_nada(self):
        crear_pedido("7004", courier=Courier.CHIBRA)
        self.client.force_login(self.logi)
        resp = self.client.post("/pedidos/lote/duplicar/", {"ids": []})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Pedido.objects.count(), 1)
