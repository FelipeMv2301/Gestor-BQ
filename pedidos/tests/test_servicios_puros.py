"""Funciones de pedidos/services.py que no llaman a SAP/Woo/Chibra — lógica pura + DB local."""
import datetime
from unittest.mock import patch
from django.test import TestCase
from pedidos.models import Pedido, SkuCourier
from pedidosRechazados.models import PedidoRechazado
from pedidos import services
from utils import Courier
from .factories import crear_pedido


class OpcionesCourierServicioTest(TestCase):
    def test_sin_sku_courier_solo_trae_placeholder_y_couriers_sin_servicio(self):
        opciones = services.opciones_courier_servicio()
        self.assertEqual(opciones[0], ("", "— Sin courier —"))
        self.assertIn(("CHIBRA", "Chibra (elegir servicio)"), opciones)

    def test_con_servicio_configurado_agrega_opcion_combinada(self):
        SkuCourier.objects.create(sku="ABC123", courier=Courier.CHIBRA, servicio_codigo="10", servicio_nombre="Express")
        opciones = services.opciones_courier_servicio()
        self.assertIn(("CHIBRA|10", "Chibra — Express"), opciones)

    def test_filas_sin_servicio_no_generan_opcion_combinada(self):
        SkuCourier.objects.create(sku="SINSERV", courier=Courier.CHIBRA, servicio_codigo="", servicio_nombre="")
        opciones = services.opciones_courier_servicio()
        self.assertNotIn(("CHIBRA|", "Chibra — "), opciones)


class DetectarCourierSapTest(TestCase):
    def setUp(self):
        SkuCourier.objects.create(sku="ABC123", courier=Courier.CHIBRA, servicio_codigo="10", servicio_nombre="Express")
        self.mapa = services._armar_mapa_sku()

    def test_sku_conocido_devuelve_courier_y_servicio(self):
        orden = {"DocumentLines": [{"ItemCode": "abc123"}]}  # minúsculas: SAP no garantiza mayúsculas
        resultado = services.detectar_courier_sap(orden, self.mapa)
        self.assertEqual(resultado, {"courier": Courier.CHIBRA, "servicio_codigo": "10", "servicio_nombre": "Express"})

    def test_sku_desconocido_devuelve_vacio(self):
        orden = {"DocumentLines": [{"ItemCode": "NOEXISTE"}]}
        resultado = services.detectar_courier_sap(orden, self.mapa)
        self.assertEqual(resultado, {"courier": "", "servicio_codigo": "", "servicio_nombre": ""})

    def test_sin_lineas_devuelve_vacio(self):
        self.assertEqual(services.detectar_courier_sap({}, self.mapa),
                          {"courier": "", "servicio_codigo": "", "servicio_nombre": ""})

    def test_primera_linea_conocida_gana(self):
        orden = {"DocumentLines": [{"ItemCode": "NOEXISTE"}, {"ItemCode": "ABC123"}]}
        resultado = services.detectar_courier_sap(orden, self.mapa)
        self.assertEqual(resultado["courier"], Courier.CHIBRA)


class DefinirTipoEntregaTest(TestCase):
    def test_sap_transportation_code_3_es_retiro(self):
        self.assertEqual(services.definir_tipo_entrega_sap({"TransportationCode": 3}), Pedido.TipoEntrega.RETIRO_BIOQUIMICA)

    def test_sap_otro_codigo_es_despacho(self):
        self.assertEqual(services.definir_tipo_entrega_sap({"TransportationCode": 1}), Pedido.TipoEntrega.DESPACHO)
        self.assertEqual(services.definir_tipo_entrega_sap({}), Pedido.TipoEntrega.DESPACHO)

    def test_woo_metodo_pickup_es_retiro(self):
        pedido_woo = {"shipping_lines": [{"method_id": "local_pickup"}]}
        self.assertEqual(services.definir_tipo_entrega_woo(pedido_woo), Pedido.TipoEntrega.RETIRO_BIOQUIMICA)

    def test_woo_sin_shipping_lines_es_despacho(self):
        self.assertEqual(services.definir_tipo_entrega_woo({}), Pedido.TipoEntrega.DESPACHO)

    def test_woo_metodo_distinto_es_despacho(self):
        pedido_woo = {"shipping_lines": [{"method_id": "flat_rate"}]}
        self.assertEqual(services.definir_tipo_entrega_woo(pedido_woo), Pedido.TipoEntrega.DESPACHO)


class ObtenerDatosContactoSapTest(TestCase):
    """El nombre de contacto sale de FirstName/LastName (OCPR) — nunca de Name, que a veces
    trae la razón social en vez de la persona. cache_bp precargado: no llama a SAP de verdad."""

    def test_nombre_sale_de_firstname_lastname_no_de_name(self):
        orden = {"CardCode": "C001", "ContactPersonCode": 1}
        cache_bp = {"C001": {
            "EmailAddress": "empresa@cliente.cl", "Phone1": "222333444",
            "ContactEmployees": [{"InternalCode": 1, "Name": "Cliente SPA", "FirstName": "Juan",
                                   "LastName": "Pérez", "E_Mail": "juan@cliente.cl", "MobilePhone": "912345678"}],
        }}
        nombre, telefono, email = services.obtener_datos_contacto_sap(orden, cache_bp, cookies={})
        self.assertEqual(nombre, "Juan Pérez")
        self.assertEqual(telefono, "912345678")
        self.assertEqual(email, "juan@cliente.cl")

    def test_sin_contacto_que_matchee_nombre_queda_vacio(self):
        orden = {"CardCode": "C002", "ContactPersonCode": 99}
        cache_bp = {"C002": {"EmailAddress": "empresa@cliente.cl", "Phone1": "222333444",
                              "ContactEmployees": [{"InternalCode": 1, "FirstName": "Juan", "LastName": "Pérez"}]}}
        nombre, telefono, email = services.obtener_datos_contacto_sap(orden, cache_bp, cookies={})
        self.assertEqual(nombre, "")
        self.assertEqual(telefono, "222333444")   # cae al Phone1 del business partner
        self.assertEqual(email, "empresa@cliente.cl")

    def test_sin_apellido_no_deja_espacio_colgando(self):
        orden = {"CardCode": "C003", "ContactPersonCode": 1}
        cache_bp = {"C003": {"ContactEmployees": [{"InternalCode": 1, "FirstName": "Juan", "LastName": ""}]}}
        nombre, telefono, email = services.obtener_datos_contacto_sap(orden, cache_bp, cookies={})
        self.assertEqual(nombre, "Juan")


class LimpiarRutSapTest(TestCase):
    def test_prefijo_cn_se_quita(self):
        self.assertEqual(services.limpiar_rut_sap("CN12345678-9"), "12345678-9")

    def test_prefijo_cn_minuscula_tambien(self):
        self.assertEqual(services.limpiar_rut_sap("cn12345678-9"), "12345678-9")

    def test_sin_prefijo_queda_igual(self):
        self.assertEqual(services.limpiar_rut_sap("12345678-9"), "12345678-9")

    def test_vacio_devuelve_vacio(self):
        self.assertEqual(services.limpiar_rut_sap(""), "")
        self.assertEqual(services.limpiar_rut_sap(None), "")

    def test_con_espacios_se_recortan(self):
        self.assertEqual(services.limpiar_rut_sap("  12345678-9  "), "12345678-9")


class PedidoYaExisteORechazadoTest(TestCase):
    def test_pedido_ya_existe(self):
        crear_pedido("2001", origen=Pedido.Origen.SAP)
        self.assertTrue(services.pedido_ya_existe(Pedido.Origen.SAP, "2001"))
        self.assertFalse(services.pedido_ya_existe(Pedido.Origen.SAP, "9999"))
        self.assertFalse(services.pedido_ya_existe(Pedido.Origen.WEB, "2001"))  # mismo N°, otro origen

    def test_pedido_fue_rechazado(self):
        PedidoRechazado.objects.create(origen=Pedido.Origen.SAP, num_pedido="2002", snapshot={})
        self.assertTrue(services.pedido_fue_rechazado(Pedido.Origen.SAP, "2002"))
        self.assertFalse(services.pedido_fue_rechazado(Pedido.Origen.SAP, "9999"))


class SkuCourierNormalizaTest(TestCase):
    def test_sku_se_guarda_en_mayusculas_y_sin_espacios(self):
        sku = SkuCourier.objects.create(sku="  abc123  ", courier=Courier.CHIBRA)
        self.assertEqual(sku.sku, "ABC123")


class SincronizarRecienteTest(TestCase):
    """Verifica que el cron delega con el rango ayer+hoy en el formato que cada integración espera
    (SAP: fecha simple; Woo: datetime ISO con hora) — sin llamar a SAP/Woo reales."""

    def test_sap_usa_fechas_simples_ayer_hoy(self):
        hoy = datetime.date.today()
        ayer = hoy - datetime.timedelta(days=1)
        with patch("pedidos.services.guardar_pedidos_sap") as mock_guardar:
            mock_guardar.return_value = {"creados": 0, "omitidos": 0}
            services.sincronizar_sap_reciente()
        mock_guardar.assert_called_once_with(after=ayer.isoformat(), before=hoy.isoformat())

    def test_woo_usa_datetime_con_hora_ayer_hoy(self):
        hoy = datetime.date.today()
        ayer = hoy - datetime.timedelta(days=1)
        with patch("pedidos.services.guardar_pedidos_woo") as mock_guardar:
            mock_guardar.return_value = {"creados": 0, "omitidos": 0}
            services.sincronizar_woo_reciente()
        mock_guardar.assert_called_once_with(
            after=f"{ayer.isoformat()}T00:00:00", before=f"{hoy.isoformat()}T23:59:59")
