"""Funciones de pedidos/services.py que sí llaman a SAP/Woo, pero mockeadas en la frontera
(integraciones.woo_client / integraciones.sap_client) — nunca pegan a la red real."""
from unittest.mock import patch
from django.test import TestCase
from django.conf import settings
from pedidos.models import Pedido
from pedidosRechazados.models import PedidoRechazado
from pedidos import services
from .factories import crear_ejecutivo, crear_pedido


def _pedido_woo(number="5001", **overrides):
    base = {
        "number": number,
        "billing": {"tax_id": "11111111-1", "company": "Cliente SPA", "first_name": "Juan",
                     "last_name": "Pérez", "phone": "912345678", "email": "juan@cliente.cl"},
        "shipping": {"address_1": "Calle 1", "address_2": "", "state": "RM", "city": "Santiago"},
        "shipping_lines": [{"method_id": "flat_rate"}],
        "customer_note": "",
    }
    base.update(overrides)
    return base


def _orden_sap(docnum="8001", **overrides):
    base = {
        "DocNum": docnum,
        "TransportationCode": 1,
        "U_BQ_TipoEntrega": "HOME",
        "U_BQ_CrearEnvio": "Y",
        "CardCode": "CN12345678-9",
        "CardName": "Cliente SPA",
        "AddressExtension": {"ShipToStreet": "Calle 1", "ShipToCounty": "Santiago", "ShipToCity": "Santiago"},
        "SalesPersonCode": 10,
        "Comments": "",
        "ContactPersonCode": 1,
        "DocumentLines": [],
    }
    base.update(overrides)
    return base


def _business_partner():
    return {
        "EmailAddress": "empresa@cliente.cl", "Phone1": "222333444",
        # Name se ignora a propósito (a veces trae la razón social, no la persona) — el contacto
        # real sale de FirstName/LastName (OCPR), nunca de Name.
        "ContactEmployees": [{"InternalCode": 1, "Name": "Cliente SPA", "FirstName": "Juan", "LastName": "Pérez",
                               "E_Mail": "juan@cliente.cl", "MobilePhone": "912345678"}],
    }


class GuardarPedidosWooTest(TestCase):
    def setUp(self):
        self.ejecutivo_web = crear_ejecutivo(codigo_sap=settings.EJECUTIVO_WEB_SAP, nombre="Ejecutivo Web")

    def test_crea_pedido_nuevo(self):
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_pedidos_woo",
                   side_effect=[[_pedido_woo("5001")], []]) as mock_obtener:
            resultado = services.guardar_pedidos_woo(after="2026-01-01T00:00:00", before="2026-01-02T23:59:59")

        self.assertEqual(resultado, {"creados": 1, "omitidos": 0})
        pedido = Pedido.objects.get(origen=Pedido.Origen.WEB, num_pedido="5001")
        self.assertEqual(pedido.rut, "11111111-1")
        self.assertEqual(pedido.ejecutivo, self.ejecutivo_web)
        # se llamó una vez por status (processing, completed)
        self.assertEqual(mock_obtener.call_count, 2)

    def test_omite_pedido_que_ya_existe(self):
        crear_pedido("5002", origen=Pedido.Origen.WEB)
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_pedidos_woo",
                   side_effect=[[_pedido_woo("5002")], []]):
            resultado = services.guardar_pedidos_woo()
        self.assertEqual(resultado, {"creados": 0, "omitidos": 1})
        self.assertEqual(Pedido.objects.filter(origen=Pedido.Origen.WEB, num_pedido="5002").count(), 1)

    def test_omite_pedido_ya_rechazado(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.WEB, num_pedido="5003", snapshot={})
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_pedidos_woo",
                   side_effect=[[_pedido_woo("5003")], []]):
            resultado = services.guardar_pedidos_woo()
        self.assertEqual(resultado, {"creados": 0, "omitidos": 1})
        self.assertFalse(Pedido.objects.filter(origen=Pedido.Origen.WEB, num_pedido="5003").exists())


class GuardarUnPedidoWooTest(TestCase):
    def setUp(self):
        crear_ejecutivo(codigo_sap=settings.EJECUTIVO_WEB_SAP, nombre="Ejecutivo Web")

    def test_crea_pedido_individual(self):
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=_pedido_woo("6001")):
            services.guardar_un_pedido_woo("6001")
        self.assertTrue(Pedido.objects.filter(origen=Pedido.Origen.WEB, num_pedido="6001").exists())

    def test_pedido_inexistente_en_woo_lanza_error(self):
        with patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=None):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_woo("9999")

    def test_pedido_ya_existente_lanza_error(self):
        crear_pedido("6002", origen=Pedido.Origen.WEB)
        with patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=_pedido_woo("6002")):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_woo("6002")

    def test_pedido_rechazado_sin_ignorar_lanza_error(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.WEB, num_pedido="6003", snapshot={})
        with patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=_pedido_woo("6003")):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_woo("6003", ignorar_rechazado=False)

    def test_pedido_rechazado_ignorando_se_crea(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.WEB, num_pedido="6004", snapshot={})
        with patch("pedidos.services.woo_client.obtener_mapa_comunas", return_value={}), \
             patch("pedidos.services.woo_client.obtener_un_pedido_woo", return_value=_pedido_woo("6004")):
            services.guardar_un_pedido_woo("6004", ignorar_rechazado=True)
        self.assertTrue(Pedido.objects.filter(origen=Pedido.Origen.WEB, num_pedido="6004").exists())


class GuardarPedidosSapTest(TestCase):
    def setUp(self):
        self.ejecutivo = crear_ejecutivo(codigo_sap=10, nombre="Elsa Martínez")

    def _mockear(self, ordenes):
        return (
            patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}),
            patch("pedidos.services.sap_client.obtener_todas_las_paginas", return_value=ordenes),
            patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()),
        )

    def test_crea_pedido_nuevo_con_datos_de_contacto(self):
        m1, m2, m3 = self._mockear([_orden_sap("8001")])
        with m1, m2, m3:
            resultado = services.guardar_pedidos_sap(after="2026-01-01", before="2026-01-02")

        self.assertEqual(resultado, {"creados": 1, "omitidos": 0, "fallidos": 0})
        pedido = Pedido.objects.get(origen=Pedido.Origen.SAP, num_pedido="8001")
        self.assertEqual(pedido.rut, "12345678-9")  # limpiar_rut_sap le quita el prefijo CN
        self.assertEqual(pedido.ejecutivo, self.ejecutivo)
        self.assertEqual(pedido.nombre_contacto, "Juan Pérez")
        self.assertEqual(pedido.tipo_entrega, Pedido.TipoEntrega.DESPACHO)

    def test_omite_pedido_que_ya_existe(self):
        crear_pedido("8002", origen=Pedido.Origen.SAP)
        m1, m2, m3 = self._mockear([_orden_sap("8002")])
        with m1, m2, m3:
            resultado = services.guardar_pedidos_sap()
        self.assertEqual(resultado, {"creados": 0, "omitidos": 1, "fallidos": 0})

    def test_omite_pedido_ya_rechazado(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="8003", snapshot={})
        m1, m2, m3 = self._mockear([_orden_sap("8003")])
        with m1, m2, m3:
            resultado = services.guardar_pedidos_sap()
        self.assertEqual(resultado, {"creados": 0, "omitidos": 1, "fallidos": 0})
        self.assertFalse(Pedido.objects.filter(origen=Pedido.Origen.SAP, num_pedido="8003").exists())

    def test_retiro_bioquimica_por_transportation_code_3(self):
        m1, m2, m3 = self._mockear([_orden_sap("8004", TransportationCode=3)])
        with m1, m2, m3:
            services.guardar_pedidos_sap()
        pedido = Pedido.objects.get(num_pedido="8004")
        self.assertEqual(pedido.tipo_entrega, Pedido.TipoEntrega.RETIRO_BIOQUIMICA)

    def test_el_filtro_no_exige_crear_envio_para_los_retiros(self):
        """Decisión 2026-08-13: un retiro en Bioquímica (TransportationCode 3) entra aunque
        U_BQ_CrearEnvio esté en 'N' — en un retiro no hay envío que crear. El flag solo restringe
        la rama de courier. Se afirma por rama, no la cadena completa, para no ser frágil."""
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_todas_las_paginas",
                   return_value=[]) as mock_paginas:
            services.guardar_pedidos_sap(after="2026-01-01")

        filtro = mock_paginas.call_args[0][1]["$filter"]
        rama_retiro, _, rama_courier = filtro.partition(" or ")
        self.assertIn("TransportationCode eq 3", rama_retiro)
        self.assertNotIn("U_BQ_CrearEnvio", rama_retiro)
        #Sin el flag, esta rama queda sin compuerta: al menos no traer los retiros anulados.
        self.assertIn("Cancelled eq 'tNO'", rama_retiro)
        self.assertIn("U_BQ_CrearEnvio eq 'Y'", rama_courier)

    def test_direccion_nula_en_sap_se_guarda_como_texto_vacio(self):
        """NV real 2601790 (2026-08-13): SAP manda las claves de AddressExtension PRESENTES pero en
        null cuando la NV no tiene dirección de destino. `.get(clave, "")` devolvía None (el default
        solo aplica si la clave falta), y None en un CharField sin null=True es NotNullViolation en
        Postgres — reventaba la ingesta completa."""
        orden = _orden_sap("8005", AddressExtension={
            "ShipToStreet": None, "ShipToCounty": None, "ShipToCity": None})
        m1, m2, m3 = self._mockear([orden])
        with m1, m2, m3:
            resultado = services.guardar_pedidos_sap()

        self.assertEqual(resultado, {"creados": 1, "omitidos": 0, "fallidos": 0})
        pedido = Pedido.objects.get(num_pedido="8005")
        self.assertEqual(pedido.direccion_calle, "")
        self.assertEqual(pedido.direccion_comuna, "")
        self.assertEqual(pedido.direccion_ciudad, "")

    def test_una_nv_con_error_no_aborta_el_lote(self):
        """Antes, una sola NV que fallara abortaba el `for` y las órdenes SIGUIENTES no se procesaban
        nunca. La clave de este test es la última aserción: la NV posterior al fallo sí entra."""
        mapear_real = services._mapear_orden_sap

        def mapear_fallando_la_del_medio(orden, *args, **kwargs):
            if str(orden.get("DocNum")) == "8007":
                raise ValueError("dato inesperado de SAP")
            return mapear_real(orden, *args, **kwargs)

        m1, m2, m3 = self._mockear([_orden_sap("8006"), _orden_sap("8007"), _orden_sap("8008")])
        with m1, m2, m3, patch("pedidos.services._mapear_orden_sap",
                               side_effect=mapear_fallando_la_del_medio):
            resultado = services.guardar_pedidos_sap()

        self.assertEqual(resultado, {"creados": 2, "omitidos": 0, "fallidos": 1})
        self.assertTrue(Pedido.objects.filter(num_pedido="8006").exists())
        self.assertFalse(Pedido.objects.filter(num_pedido="8007").exists())
        self.assertTrue(Pedido.objects.filter(num_pedido="8008").exists())


class GuardarUnPedidoSapTest(TestCase):
    def setUp(self):
        crear_ejecutivo(codigo_sap=10, nombre="Elsa Martínez")

    def test_crea_pedido_individual(self):
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9001")), \
             patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()):
            services.guardar_un_pedido_sap("9001")
        self.assertTrue(Pedido.objects.filter(origen=Pedido.Origen.SAP, num_pedido="9001").exists())

    def test_pedido_inexistente_en_sap_lanza_error(self):
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=None):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_sap("9999")

    def test_pedido_ya_existente_lanza_error(self):
        crear_pedido("9002", origen=Pedido.Origen.SAP)
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9002")):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_sap("9002")

    def test_pedido_rechazado_sin_ignorar_lanza_error(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="9003", snapshot={})
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9003")):
            with self.assertRaises(ValueError):
                services.guardar_un_pedido_sap("9003", ignorar_rechazado=False)

    def test_pedido_rechazado_ignorando_se_crea(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="9004", snapshot={})
        with patch("pedidos.services.sap_client.obtener_cookies_sap", return_value={}), \
             patch("pedidos.services.sap_client.obtener_un_resultado", return_value=_orden_sap("9004")), \
             patch("pedidos.services.sap_client.obtener_business_partner", return_value=_business_partner()):
            services.guardar_un_pedido_sap("9004", ignorar_rechazado=True)
        self.assertTrue(Pedido.objects.filter(origen=Pedido.Origen.SAP, num_pedido="9004").exists())


class ReingresarPedidoTest(TestCase):
    def test_reingresa_desde_sap_y_borra_archivo(self):
        rechazado = PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="7001", snapshot={})
        with patch("pedidos.services.guardar_un_pedido_sap", return_value="ok") as mock_sap:
            services.reingresar_pedido(rechazado)
        mock_sap.assert_called_once_with("7001", ignorar_rechazado=True)
        self.assertFalse(PedidoRechazado.objects.filter(pk=rechazado.pk).exists())

    def test_reingresa_desde_woo_y_borra_archivo(self):
        rechazado = PedidoRechazado.objects.create(origen=Pedido.Origen.WEB, num_pedido="7002", snapshot={})
        with patch("pedidos.services.guardar_un_pedido_woo", return_value="ok") as mock_woo:
            services.reingresar_pedido(rechazado)
        mock_woo.assert_called_once_with("7002", ignorar_rechazado=True)
        self.assertFalse(PedidoRechazado.objects.filter(pk=rechazado.pk).exists())

    def test_si_la_reingesta_falla_no_borra_el_archivo(self):
        rechazado = PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="7003", snapshot={})
        with patch("pedidos.services.guardar_un_pedido_sap", side_effect=ValueError("SAP caído")):
            with self.assertRaises(ValueError):
                services.reingresar_pedido(rechazado)
        self.assertTrue(PedidoRechazado.objects.filter(pk=rechazado.pk).exists())
