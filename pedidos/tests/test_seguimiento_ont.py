"""Módulo de Seguimiento ONT: creación automática (pedidos/services.py) y permisos (pedidos/permisos.py).
Las vistas propias del módulo se testean en seguimientoOnt/tests.py."""
from unittest.mock import patch
from django.test import TestCase
from django.conf import settings
from cuentas.models import PerfilUsuario
from seguimientoOnt.models import DespachoOnt
from pedidos import services, permisos
from pedidos.models import Pedido
from .factories import crear_ejecutivo, crear_pedido, crear_usuario
from .test_integraciones_mockeadas import _orden_sap, _pedido_woo, _business_partner

Rol = PerfilUsuario.Rol


class CrearSeguimientoOntSiCorrespondeTest(TestCase):
    def test_crea_si_el_ejecutivo_es_ont(self):
        ejecutivo = crear_ejecutivo(codigo_sap=44, es_ont=True)
        pedido = crear_pedido("3001", ejecutivo=ejecutivo)
        services.crear_seguimiento_ont_si_corresponde(pedido)
        self.assertTrue(DespachoOnt.objects.filter(pedido=pedido).exists())

    def test_no_crea_si_el_ejecutivo_no_es_ont(self):
        ejecutivo = crear_ejecutivo(codigo_sap=99, es_ont=False)
        pedido = crear_pedido("3002", ejecutivo=ejecutivo)
        services.crear_seguimiento_ont_si_corresponde(pedido)
        self.assertFalse(DespachoOnt.objects.filter(pedido=pedido).exists())

    def test_no_crea_si_el_pedido_no_tiene_ejecutivo(self):
        pedido = crear_pedido("3003", ejecutivo=None)
        services.crear_seguimiento_ont_si_corresponde(pedido)
        self.assertFalse(DespachoOnt.objects.filter(pedido=pedido).exists())

    def test_no_duplica_si_ya_existe(self):
        ejecutivo = crear_ejecutivo(codigo_sap=44, es_ont=True)
        pedido = crear_pedido("3004", ejecutivo=ejecutivo)
        services.crear_seguimiento_ont_si_corresponde(pedido)
        services.crear_seguimiento_ont_si_corresponde(pedido)
        self.assertEqual(DespachoOnt.objects.filter(pedido=pedido).count(), 1)


class PropiedadesDespachoOntTest(TestCase):
    def test_propiedades_reflejan_el_pedido_en_vivo(self):
        ejecutivo = crear_ejecutivo(codigo_sap=44, es_ont=True)
        pedido = crear_pedido(
            "3005", ejecutivo=ejecutivo, courier="CHIBRA",
            nombre_contacto="Juan Pérez", telefono_contacto="+56911112222",
            direccion_calle="Calle 1", direccion_comuna="Providencia", direccion_ciudad="Santiago",
            observaciones="Frágil",
        )
        seguimiento = DespachoOnt.objects.create(pedido=pedido)

        self.assertEqual(seguimiento.courier, "Chibra")
        self.assertEqual(seguimiento.ot, "")  # sin envío todavía
        self.assertEqual(seguimiento.nombre_contacto, "Juan Pérez")
        self.assertEqual(seguimiento.telefono_contacto, "+56911112222")
        self.assertEqual(seguimiento.ciudad_destino, "Santiago")
        self.assertEqual(seguimiento.direccion_destino, "Calle 1, Providencia, Santiago")
        self.assertEqual(seguimiento.observaciones, "Frágil")

        # Si el pedido se edita después, el seguimiento lo refleja solo (no hay nada que sincronizar).
        pedido.nombre_contacto = "Otro Nombre"
        pedido.save(update_fields=["nombre_contacto"])
        seguimiento.refresh_from_db()
        self.assertEqual(seguimiento.nombre_contacto, "Otro Nombre")


class GuardarUnPedidoSapCreaSeguimientoOntTest(TestCase):
    def test_crea_seguimiento_si_el_ejecutivo_es_ont(self):
        crear_ejecutivo(codigo_sap=10, es_ont=True)
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9101")), \
             patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()):
            services.guardar_un_pedido_sap("9101")

        pedido = Pedido.objects.get(origen=Pedido.Origen.SAP, num_pedido="9101")
        self.assertTrue(DespachoOnt.objects.filter(pedido=pedido).exists())

    def test_no_crea_seguimiento_si_el_ejecutivo_no_es_ont(self):
        crear_ejecutivo(codigo_sap=10, es_ont=False)
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9102")), \
             patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()):
            services.guardar_un_pedido_sap("9102")

        pedido = Pedido.objects.get(origen=Pedido.Origen.SAP, num_pedido="9102")
        self.assertFalse(DespachoOnt.objects.filter(pedido=pedido).exists())


class GuardarPedidosSapLoteCreaSeguimientoOntTest(TestCase):
    def test_crea_solo_para_los_pedidos_del_ejecutivo_ont(self):
        crear_ejecutivo(codigo_sap=10, es_ont=True)
        crear_ejecutivo(codigo_sap=20, es_ont=False)
        ordenes = [_orden_sap("9201", SalesPersonCode=10), _orden_sap("9202", SalesPersonCode=20)]
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_todas_las_paginas", return_value=ordenes), \
             patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()):
            services.guardar_pedidos_sap()

        p_ont = Pedido.objects.get(num_pedido="9201")
        p_no_ont = Pedido.objects.get(num_pedido="9202")
        self.assertTrue(DespachoOnt.objects.filter(pedido=p_ont).exists())
        self.assertFalse(DespachoOnt.objects.filter(pedido=p_no_ont).exists())


class GuardarPedidoWooCreaSeguimientoOntTest(TestCase):
    def setUp(self):
        self.ejecutivo_web = crear_ejecutivo(codigo_sap=settings.EJECUTIVO_WEB_SAP, es_ont=True)

    def test_guardar_un_pedido_woo_crea_seguimiento(self):
        with patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=_pedido_woo("6101")), \
             patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}):
            services.guardar_un_pedido_woo("6101")

        pedido = Pedido.objects.get(origen=Pedido.Origen.WEB, num_pedido="6101")
        self.assertTrue(DespachoOnt.objects.filter(pedido=pedido).exists())

    def test_guardar_pedidos_woo_lote_crea_seguimiento(self):
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_pedidos_woo",
                   side_effect=[[_pedido_woo("6102")], []]):
            services.guardar_pedidos_woo()

        pedido = Pedido.objects.get(origen=Pedido.Origen.WEB, num_pedido="6102")
        self.assertTrue(DespachoOnt.objects.filter(pedido=pedido).exists())


class DuplicarPedidoCreaSeguimientoOntTest(TestCase):
    def test_duplicar_pedido_de_ejecutivo_ont_crea_seguimiento(self):
        logi = crear_usuario("logi_ont@bioquimica.cl", Rol.LOGISTICA)
        ejecutivo = crear_ejecutivo(codigo_sap=44, es_ont=True)
        original = crear_pedido("3006", ejecutivo=ejecutivo, estado_comercial=Pedido.EstadoComercial.APROBADO)

        duplicado = services.duplicar_pedido(original, logi)

        self.assertEqual(duplicado.num_pedido, "3006-2")  # cuenta el propio original (num_pedido="3006") como existente
        self.assertTrue(DespachoOnt.objects.filter(pedido=duplicado).exists())
        self.assertFalse(DespachoOnt.objects.filter(pedido=original).exists())


class QuerysetOntTest(TestCase):
    def setUp(self):
        self.ejec_ont = crear_ejecutivo(codigo_sap=44, nombre="Ejecutivo ONT", es_ont=True)
        self.ejec_ajeno = crear_ejecutivo(codigo_sap=99, nombre="Ejecutivo Ajeno", es_ont=False)
        self.dueno = crear_usuario("dueno_ont@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=44)
        self.ajeno = crear_usuario("ajeno_ont@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        self.logi = crear_usuario("logi_ont2@bioquimica.cl", Rol.LOGISTICA)
        self.admin = crear_usuario("admin_ont@bioquimica.cl", Rol.ADMIN)

        pedido_ont = crear_pedido("3007", ejecutivo=self.ejec_ont)
        self.seguimiento = DespachoOnt.objects.create(pedido=pedido_ont)

    def test_logistica_ve_todo(self):
        self.assertIn(self.seguimiento, permisos.queryset_ont(self.logi))

    def test_admin_ve_todo(self):
        self.assertIn(self.seguimiento, permisos.queryset_ont(self.admin))

    def test_ejecutivo_ont_ve_toda_la_cola_compartida(self):
        # No solo lo suyo (código 44) — también lo de otro código ONT (equipo chico, cola compartida).
        otro_ejec_ont = crear_ejecutivo(codigo_sap=42, nombre="Otro Ejecutivo ONT", es_ont=True)
        otro_pedido = crear_pedido("3008", ejecutivo=otro_ejec_ont)
        otro_seguimiento = DespachoOnt.objects.create(pedido=otro_pedido)

        visibles = permisos.queryset_ont(self.dueno)
        self.assertIn(self.seguimiento, visibles)
        self.assertIn(otro_seguimiento, visibles)

    def test_ajeno_no_ve_nada(self):
        self.assertNotIn(self.seguimiento, permisos.queryset_ont(self.ajeno))

    def test_puede_editar_ont(self):
        self.assertTrue(permisos.puede_editar_ont(self.logi, self.seguimiento))
        self.assertTrue(permisos.puede_editar_ont(self.admin, self.seguimiento))
        self.assertTrue(permisos.puede_editar_ont(self.dueno, self.seguimiento))
        self.assertFalse(permisos.puede_editar_ont(self.ajeno, self.seguimiento))
