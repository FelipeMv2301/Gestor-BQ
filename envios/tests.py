import base64, io
from unittest.mock import patch
from pypdf import PdfWriter, PdfReader
from django.test import TestCase, RequestFactory, Client
from django.conf import settings
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos.tests.factories import crear_pedido, crear_usuario, crear_ejecutivo
from utils import Courier
from integraciones import starken_client
from .services import parsear_bultos, validar_pedidos_para_despacho, despachar_pedidos, _parsear_despacho_starken
from .models import EnvioCourier

Rol = PerfilUsuario.Rol


class EmitirOfStarkenMultibultosTest(TestCase):
    """emitir_of nunca se prueba directo en el resto de la suite (todos los tests de despacho
    mockean la función completa) — nadie ejercitaba la matemática real de multibultos hasta ahora.
    Bug real encontrado 2026-08-18: 'largo' sumaba una vez por FILA del formulario, no una vez por
    BULTO FÍSICO — una fila con cantidad=3 solo aportaba su largo una vez, subestimando el volumen
    declarado a Starken frente a la regla del manual ("sumar el total de una de las dimensiones de
    TODOS LOS BULTOS")."""

    def _destinatario(self):
        return {"nombre": "Cliente Test", "rut": "11111111-1", "direccion": "Calle 1",
                "numero": "100", "depto": "", "comuna": "Providencia",
                "telefono": "+56911112222", "email": "cliente@x.cl"}

    def _post_capturado(self, respuesta_json):
        capturado = {}

        def fake_post(url, json=None, timeout=None):
            capturado["url"] = url
            capturado["payload"] = json

            class FakeResponse:
                def raise_for_status(self):
                    pass
                def json(self):
                    return respuesta_json

            return FakeResponse()

        return capturado, fake_post

    def test_una_fila_con_varios_bultos_multiplica_largo_por_cantidad(self):
        # Una sola fila: 3 cajas idénticas de 10x5x4 cm, 2 kg cada una.
        bultos = [{"cantidad": 3, "peso": 2.0, "alto": "4", "ancho": "5", "largo": "10", "tipo_contenido": ""}]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000001})

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post):
            starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        payload = capturado["payload"]
        self.assertEqual(payload["largo"], "30.0")   # 10 cm x 3 bultos, NO "10.0" (el bug)
        self.assertEqual(payload["ancho"], "5.0")     # max no depende de la cantidad
        self.assertEqual(payload["alto"], "4.0")
        self.assertEqual(payload["kilosTotal"], "6.0")   # 2 kg x 3 bultos
        self.assertEqual(payload["cantidadEncargo1"], "3")

    def test_varias_filas_distintas_combina_suma_y_maximo_correctamente(self):
        # Fila 1: 2 bultos de 10x20x5 cm. Fila 2: 1 bulto de 5x8x15 cm.
        bultos = [
            {"cantidad": 2, "peso": 1.0, "alto": "5", "ancho": "20", "largo": "10", "tipo_contenido": ""},
            {"cantidad": 1, "peso": 3.0, "alto": "15", "ancho": "8", "largo": "5", "tipo_contenido": ""},
        ]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000002})

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post):
            starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        payload = capturado["payload"]
        self.assertEqual(payload["largo"], "25.0")   # (10x2) + (5x1) = 25 — suma por bulto físico
        self.assertEqual(payload["ancho"], "20.0")    # max(20, 8) = 20, invariante a la cantidad
        self.assertEqual(payload["alto"], "15.0")     # max(5, 15) = 15
        self.assertEqual(payload["kilosTotal"], "5.0")   # (1x2) + (3x1) = 5
        self.assertEqual(payload["cantidadEncargo1"], "3")   # 2 + 1 bultos físicos

    def test_dv_destinatario_se_normaliza_a_mayuscula(self):
        # Bug real encontrado 2026-08-18: dvRutDestinatario se mandaba tal cual lo tipeara Logística
        # (ej. "k" minúscula) — validar_rut() lo acepta igual, pero el manual siempre lo muestra en
        # mayúscula ("K").
        destinatario = self._destinatario()
        destinatario["rut"] = "8765432-k"
        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000003})

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post):
            starken_client.emitir_of([], bultos, destinatario, {"servicio": "0"})

        self.assertEqual(capturado["payload"]["dvRutDestinatario"], "K")

    def test_departamento_remitente_viaja_desde_settings(self):
        # Antes iba fijo en "" — el diccionario de parámetros de Starken confirma que es un campo
        # real (se hace eco en la respuesta como departamentoDireccionRemitente).
        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000004})

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post), \
             patch.object(settings, "STARKEN_DEPARTAMENTO_REMITENTE", "Sección 4 S-2"):
            starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        self.assertEqual(capturado["payload"]["departamentoRemitente"], "Sección 4 S-2")

    def test_valor_declarado_alto_sin_documento_lanza_error_claro(self):
        # Diccionario de Entrada: "If the value exceeds 50000, it must be accompanied by a reference
        # document." — lo validamos nosotros antes de llamar a Starken, con un mensaje en español.
        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]

        with self.assertRaises(ValueError) as ctx:
            starken_client.emitir_of([], bultos, self._destinatario(),
                                    {"servicio": "0", "valor_declarado": 60000, "documentos": []})
        self.assertIn("50.000", str(ctx.exception))
        self.assertIn("documento de referencia", str(ctx.exception))

    def test_valor_declarado_alto_con_documento_no_lanza_error(self):
        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000005})
        documentos = [{"tipo": "26", "numero": "12345"}]

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post):
            starken_client.emitir_of([], bultos, self._destinatario(),
                                    {"servicio": "0", "valor_declarado": 60000, "documentos": documentos})

        self.assertEqual(capturado["payload"]["valorDeclarado"], "60000")

    def test_error_de_red_se_traduce_a_mensaje_claro(self):
        import requests

        def fake_post_caido(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("Max retries exceeded with url: ...")

        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        with patch("integraciones.starken_client.requests.post", side_effect=fake_post_caido):
            with self.assertRaises(ValueError) as ctx:
                starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        mensaje = str(ctx.exception)
        self.assertNotIn("ConnectionError", mensaje)
        self.assertNotIn("Max retries", mensaje)
        self.assertIn("Starken", mensaje)


class ParsearBultosTest(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_modo_simple_divide_peso_entre_cantidad(self):
        r = self.rf.post("/x", {
            "modo_bultos": "simple", "simple_cantidad": "2",
            "simple_peso_total": "5", "simple_tipo_contenido": "SECO",
        })
        bultos = parsear_bultos(r)
        self.assertEqual(bultos, [{
            "tipo": "CAJA", "cantidad": 2, "alto": "", "ancho": "", "largo": "",
            "peso": 2.5, "tipo_contenido": "SECO",
        }])

    def test_modo_simple_cantidad_cero_no_divide_por_cero(self):
        r = self.rf.post("/x", {
            "modo_bultos": "simple", "simple_cantidad": "0",
            "simple_peso_total": "5", "simple_tipo_contenido": "SECO",
        })
        bultos = parsear_bultos(r)
        self.assertEqual(bultos[0]["peso"], 5)  # sin cantidad, usa el peso total tal cual

    def test_modo_detallado_varios_bultos(self):
        r = self.rf.post("/x", {
            "modo_bultos": "detallado",
            "bulto_tipo": ["CAJA", "PALLET"],
            "bulto_cantidad": ["1", "3"],
            "bulto_alto": ["", "10"],
            "bulto_ancho": ["", "20"],
            "bulto_largo": ["", "30"],
            "bulto_peso": ["2.5", "4.0"],
            "bulto_tipo_contenido": ["SECO", "REFRIGERADO"],
        })
        bultos = parsear_bultos(r)
        self.assertEqual(len(bultos), 2)
        self.assertEqual(bultos[1], {
            "tipo": "PALLET", "cantidad": 3, "alto": "10", "ancho": "20", "largo": "30",
            "peso": 4.0, "tipo_contenido": "REFRIGERADO",
        })


def _post_starken(rf, extra=None):
    datos = {
        "modo_bultos": "detallado",
        "bulto_tipo": ["CAJA"], "bulto_cantidad": ["1"],
        "bulto_alto": ["5"], "bulto_ancho": ["25"], "bulto_largo": ["11"],
        "bulto_peso": ["2.0"], "bulto_tipo_contenido": [""],
        "destinatario_nombre": "Juan Pérez", "destinatario_rut": "11111111-1",
        "destinatario_telefono": "+56911112222", "destinatario_email": "juan@cliente.cl",
    }
    datos.update(extra or {})
    return rf.post("/x", datos)


class ParsearDespachoStarkenTest(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_domicilio_sin_direccion_falla(self):
        r = _post_starken(self.rf, {"starken_calle": "", "starken_numero": "", "destinatario_comuna": ""})
        with self.assertRaises(ValueError):
            _parsear_despacho_starken(r)

    def test_domicilio_con_direccion_completa_pasa(self):
        r = _post_starken(self.rf, {
            "starken_calle": "Av. Providencia", "starken_numero": "123", "destinatario_comuna": "Providencia",
        })
        bultos, destinatario, datos_courier = _parsear_despacho_starken(r)
        self.assertEqual(destinatario["direccion"], "Av. Providencia")
        self.assertIsNone(datos_courier["codigo_agencia_destino"])

    def test_agencia_sin_direccion_pasa(self):
        r = _post_starken(self.rf, {
            "codigo_agencia_destino": "1467",
            "starken_calle": "", "starken_numero": "", "destinatario_comuna": "",
        })
        bultos, destinatario, datos_courier = _parsear_despacho_starken(r)
        self.assertEqual(datos_courier["codigo_agencia_destino"], "1467")
        self.assertEqual(destinatario["direccion"], "")

    def test_agencia_sin_nombre_sigue_fallando(self):
        r = _post_starken(self.rf, {
            "codigo_agencia_destino": "1467", "destinatario_nombre": "",
            "starken_calle": "", "starken_numero": "", "destinatario_comuna": "",
        })
        with self.assertRaises(ValueError):
            _parsear_despacho_starken(r)


class ValidarPedidosParaDespachoTest(TestCase):
    def setUp(self):
        self.aprobado = dict(
            estado_comercial=Pedido.EstadoComercial.APROBADO, courier=Courier.CHIBRA, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_lista_vacia_falla(self):
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([])

    def test_ok_devuelve_courier_comun(self):
        p1 = crear_pedido("1001", **self.aprobado)
        p2 = crear_pedido("1002", **self.aprobado)
        self.assertEqual(validar_pedidos_para_despacho([p1, p2]), Courier.CHIBRA)

    def test_ruts_distintos_falla(self):
        p1 = crear_pedido("1003", **self.aprobado)
        p2 = crear_pedido("1004", **{**self.aprobado, "rut": "22222222-2"})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1, p2])

    def test_couriers_distintos_falla(self):
        p1 = crear_pedido("1005", **self.aprobado)
        p2 = crear_pedido("1006", **{**self.aprobado, "courier": "OTRO_COURIER"})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1, p2])

    def test_sin_courier_falla(self):
        p1 = crear_pedido("1007", **{**self.aprobado, "courier": ""})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1])

    def test_no_aprobado_falla(self):
        p1 = crear_pedido("1008", **{**self.aprobado, "estado_comercial": Pedido.EstadoComercial.PENDIENTE})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1])

    def test_con_envio_ya_asignado_falla(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        p1 = crear_pedido("1009", **{**self.aprobado, "envio": envio})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1])

    # Chequeo movido acá desde el extinto aprobar_pedido (HU-F1.8): el corte de completitud
    # ahora se aplica al despachar, no al "aprobar" (ya no existe ese paso manual).
    def test_sin_contacto_ni_direccion_falla(self):
        p1 = crear_pedido("1010", **{**self.aprobado, "telefono_contacto": "", "direccion_calle": ""})
        with self.assertRaises(ValueError):
            validar_pedidos_para_despacho([p1])

    def test_con_email_pero_sin_telefono_pasa(self):
        p1 = crear_pedido("1011", **{**self.aprobado, "telefono_contacto": "", "email_contacto": "cliente@x.cl"})
        self.assertEqual(validar_pedidos_para_despacho([p1]), Courier.CHIBRA)


def _destinatario():
    return {"nombre": "Juan Pérez", "rut": "11111111-1", "direccion": "Calle 1",
            "comuna": "Santiago", "telefono": "912345678", "email": "juan@cliente.cl"}


def _datos_courier():
    return {"centro": "02", "servicio": "10", "valor_declarado": 0, "volumen_total": "", "observaciones": ""}


def _bultos():
    return [{"tipo": "CAJA", "cantidad": 1, "alto": "", "ancho": "", "largo": "", "peso": 2.5, "tipo_contenido": "SECO"}]


class DespacharPedidosTest(TestCase):
    def setUp(self):
        self.usuario = crear_usuario("logi@bioquimica.cl")
        self.aprobado = dict(
            estado_comercial=Pedido.EstadoComercial.APROBADO, courier=Courier.CHIBRA, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_despacho_ok_crea_envio_con_bultos_y_liga_pedidos(self):
        p1 = crear_pedido("2001", **self.aprobado)
        p2 = crear_pedido("2002", **self.aprobado)
        with patch("envios.services.chibra_client.documentar_envio", return_value={"numero_envio": "OT-123"}), \
             patch("envios.services.notificar_pedido") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.CHIBRA, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "OT-123")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(envio.datos_courier["bultos"], _bultos())  # el fix de hoy: bultos SÍ quedan guardados
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 2)

    def test_courier_sin_integracion_falla_y_no_crea_envio(self):
        p1 = crear_pedido("2003", **{**self.aprobado, "courier": "OTRO_COURIER"})
        with self.assertRaises(ValueError):
            despachar_pedidos([p1], "OTRO_COURIER", _bultos(), _destinatario(), _datos_courier(), self.usuario)
        self.assertEqual(EnvioCourier.objects.count(), 0)

    def test_notificacion_fallida_no_impide_el_despacho(self):
        p1 = crear_pedido("2004", **self.aprobado)
        with patch("envios.services.chibra_client.documentar_envio", return_value={"numero_envio": "OT-456"}), \
             patch("envios.services.notificar_pedido", side_effect=ValueError("SMTP caído")):
            envio, fallidas = despachar_pedidos([p1], Courier.CHIBRA, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertIsNotNone(envio.pk)
        p1.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)  # el despacho quedó igual, solo falló el email
        self.assertEqual(len(fallidas), 1)
        self.assertEqual(fallidas[0][0], p1)

    # No mockea chibra_client.documentar_envio a propósito: ejercita la validación real de
    # utils.validar_rut que chibra_client.py ya usa (sin test hasta ahora, agregado en paridad con Starken).
    def test_rut_invalido_falla_y_no_crea_envio(self):
        p1 = crear_pedido("2005", **self.aprobado)
        destinatario = {**_destinatario(), "rut": "11111111-9"}  # dígito verificador incorrecto
        with self.assertRaises(ValueError):
            despachar_pedidos([p1], Courier.CHIBRA, _bultos(), destinatario, _datos_courier(), self.usuario)
        self.assertEqual(EnvioCourier.objects.count(), 0)


class DespacharMoveupTest(TestCase):
    def setUp(self):
        self.usuario = crear_usuario("logi@bioquimica.cl")
        self.aprobado = dict(
            estado_comercial=Pedido.EstadoComercial.APROBADO, courier=Courier.MOVEUP, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_despacho_ok_crea_envio_y_liga_pedidos(self):
        p1 = crear_pedido("6001", **self.aprobado)
        p2 = crear_pedido("6002", **self.aprobado)
        destinatario = {**_destinatario(), "numero": "123", "depto": ""}
        with patch("envios.services.moveup_client.crear_paquetes", return_value=[{"id": 555}]), \
             patch("envios.services.notificar_pedido") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.MOVEUP, [], destinatario, _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "555")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 2)

    def test_notificacion_fallida_no_impide_el_despacho(self):
        p1 = crear_pedido("6003", **self.aprobado)
        destinatario = {**_destinatario(), "numero": "123", "depto": ""}
        with patch("envios.services.moveup_client.crear_paquetes", return_value=[{"id": 556}]), \
             patch("envios.services.notificar_pedido", side_effect=ValueError("SMTP caído")):
            envio, fallidas = despachar_pedidos([p1], Courier.MOVEUP, [], destinatario, _datos_courier(), self.usuario)

        self.assertIsNotNone(envio.pk)
        p1.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(len(fallidas), 1)
        self.assertEqual(fallidas[0][0], p1)

    def test_sin_paquetes_creados_deja_orden_transporte_vacia(self):
        p1 = crear_pedido("6004", **self.aprobado)
        destinatario = {**_destinatario(), "numero": "123", "depto": ""}
        with patch("envios.services.moveup_client.crear_paquetes", return_value=[]), \
             patch("envios.services.notificar_pedido"):
            envio, _ = despachar_pedidos([p1], Courier.MOVEUP, [], destinatario, _datos_courier(), self.usuario)
        self.assertEqual(envio.orden_transporte, "")


class DespacharStarkenTest(TestCase):
    def setUp(self):
        self.usuario = crear_usuario("logi@bioquimica.cl")
        self.aprobado = dict(
            estado_comercial=Pedido.EstadoComercial.APROBADO, courier=Courier.STARKEN, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_despacho_ok_crea_envio_con_bultos_y_liga_pedidos(self):
        p1 = crear_pedido("5001", **self.aprobado)
        p2 = crear_pedido("5002", **self.aprobado)
        with patch("envios.services.starken_client.emitir_of", return_value={"numero_orden_flete": "222607751"}), \
             patch("envios.services.notificar_pedido") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.STARKEN, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "222607751")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(envio.datos_courier["bultos"], _bultos())
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 2)

    def test_notificacion_fallida_no_impide_el_despacho(self):
        p1 = crear_pedido("5003", **self.aprobado)
        with patch("envios.services.starken_client.emitir_of", return_value={"numero_orden_flete": "222607751"}), \
             patch("envios.services.notificar_pedido", side_effect=ValueError("SMTP caído")):
            envio, fallidas = despachar_pedidos([p1], Courier.STARKEN, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertIsNotNone(envio.pk)
        p1.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(len(fallidas), 1)
        self.assertEqual(fallidas[0][0], p1)

    # No mockea starken_client.emitir_of a propósito: ejercita la validación real de
    # utils.validar_rut agregada esta sesión — debe fallar ANTES de intentar el POST a Starken.
    def test_rut_invalido_falla_y_no_crea_envio(self):
        p1 = crear_pedido("5004", **self.aprobado)
        destinatario = {**_destinatario(), "rut": "11111111-9"}  # dígito verificador incorrecto
        with self.assertRaises(ValueError):
            despachar_pedidos([p1], Courier.STARKEN, _bultos(), destinatario, _datos_courier(), self.usuario)
        self.assertEqual(EnvioCourier.objects.count(), 0)


# No hay wrapper en envios/services.py que llame a esto todavía (no está conectado a ningún view) —
# se testea el cliente directo, mockeando requests.post, mismo criterio que los dry-run manuales.
class GenerarEtiquetaTest(TestCase):
    def _fake_response(self, status=200, data=None, message="OK"):
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"status": status, "data": data or [], "message": message}
        return FakeResponse()

    def test_decodifica_las_etiquetas_en_base64(self):
        etiqueta_b64 = base64.b64encode(b"%PDF-fake").decode()
        with patch("integraciones.starken_client.requests.post",
                    return_value=self._fake_response(data=[etiqueta_b64])) as mock_post:
            resultado = starken_client.generar_etiqueta(222607751)

        self.assertEqual(resultado, [b"%PDF-fake"])
        mock_post.assert_called_once_with(
            settings.STARKEN_ETIQUETA_URL,
            auth=(settings.STARKEN_ETIQUETA_USER, settings.STARKEN_ETIQUETA_PASSWORD),
            params={"ordenFlete": 222607751, "tipoSalida": starken_client.TIPO_SALIDA_BASE64_10X10},
            timeout=30,
        )

    def test_varias_etiquetas_se_decodifican_todas(self):
        etiquetas_b64 = [base64.b64encode(b"bulto-1").decode(), base64.b64encode(b"bulto-2").decode()]
        with patch("integraciones.starken_client.requests.post",
                    return_value=self._fake_response(data=etiquetas_b64)):
            resultado = starken_client.generar_etiqueta(222607751)
        self.assertEqual(resultado, [b"bulto-1", b"bulto-2"])

    def test_status_distinto_de_200_lanza_error(self):
        with patch("integraciones.starken_client.requests.post",
                    return_value=self._fake_response(status=400, message="Orden de flete no encontrada")):
            with self.assertRaises(ValueError):
                starken_client.generar_etiqueta(999)


class DescargarDocumentoViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec_sin_pedidos = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=99)
        self.envio_starken = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="222607751")
        self.envio_chibra = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-1")

    def test_descarga_un_solo_archivo_como_pdf(self):
        # inline (no attachment): el PDF se abre en el visor nativo del navegador para poder
        # imprimirlo directo, en vez de forzar la descarga a disco.
        self.client.force_login(self.logi)
        with patch("envios.views.generar_documento", return_value=[b"%PDF-fake"]):
            resp = self.client.get(f"/envios/{self.envio_starken.pk}/documento/etiqueta/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("inline", resp["Content-Disposition"])
        self.assertEqual(resp.content, b"%PDF-fake")

    def _pdf_de_una_pagina(self):
        # PDF mínimo pero real (no bytes fake): pypdf.PdfWriter.append exige poder parsear cada
        # archivo, así que un placeholder tipo b"a" revienta con PdfStreamError.
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def test_varios_archivos_se_fusionan_en_un_solo_pdf(self):
        # Multibultos (ej. Starken con 3 bultos → 3 etiquetas): se fusionan en un PDF de N páginas
        # en vez de un .zip, para poder verlo/imprimirlo igual que el caso de un solo archivo.
        self.client.force_login(self.logi)
        archivos = [self._pdf_de_una_pagina(), self._pdf_de_una_pagina()]
        with patch("envios.views.generar_documento", return_value=archivos):
            resp = self.client.get(f"/envios/{self.envio_starken.pk}/documento/etiqueta/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("inline", resp["Content-Disposition"])
        fusionado = PdfReader(io.BytesIO(resp.content))
        self.assertEqual(len(fusionado.pages), 2)

    # No mockea generar_documento: ejercita el ValueError real de integraciones.documentos cuando
    # el courier no tiene ese tipo registrado (Chibra no está en DOCUMENTOS_COURIER).
    def test_courier_sin_ese_documento_muestra_error(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio_chibra.pk}/documento/etiqueta/")
        self.assertRedirects(resp, f"/envios/{self.envio_chibra.pk}/")

    def test_sin_orden_transporte_no_intenta_generar(self):
        self.client.force_login(self.logi)
        envio_sin_ot = EnvioCourier.objects.create(courier=Courier.STARKEN)
        with patch("envios.views.generar_documento") as mock_generar:
            resp = self.client.get(f"/envios/{envio_sin_ot.pk}/documento/etiqueta/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(mock_generar.called)

    def test_ejecutivo_sin_pedidos_en_el_envio_no_puede_descargar(self):
        self.client.force_login(self.ejec_sin_pedidos)
        with patch("envios.views.generar_documento") as mock_generar:
            resp = self.client.get(f"/envios/{self.envio_starken.pk}/documento/etiqueta/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(mock_generar.called)

    def test_detalle_envio_muestra_documentos_disponibles(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio_starken.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["documentos"], [("etiqueta", "Etiqueta de envío")])

    def test_detalle_envio_chibra_sin_documentos(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio_chibra.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["documentos"], [])


class CambiarEstadoEnvioViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA, estado=EnvioCourier.Estado.DESPACHADO)

    def test_no_logistica_no_puede_cambiar_estado(self):
        self.client.force_login(self.ejec)
        self.client.post(f"/envios/{self.envio.pk}/estado/", {"estado": "ENTREGADO"})
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.estado, EnvioCourier.Estado.DESPACHADO)

    def test_logistica_marca_entregado(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio.pk}/estado/", {"estado": "ENTREGADO"})
        self.assertEqual(resp.status_code, 302)
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.estado, EnvioCourier.Estado.ENTREGADO)

    def test_estado_invalido_no_cambia_nada(self):
        self.client.force_login(self.logi)
        self.client.post(f"/envios/{self.envio.pk}/estado/", {"estado": "LO_QUE_SEA"})
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.estado, EnvioCourier.Estado.DESPACHADO)


class EditarEnvioViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.envio = EnvioCourier.objects.create(
            courier=Courier.CHIBRA, orden_transporte="OT-1",
            datos_courier={"centro": "02", "servicio": "10", "valor_declarado": 0,
                           "observaciones": "", "bultos": _bultos()})

    def test_get_precarga_datos_actuales(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio.pk}/editar/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "OT-1")

    def test_post_actualiza_ot_y_bultos(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio.pk}/editar/", {
            "courier": Courier.CHIBRA, "orden_transporte": "OT-2",
            "centro": "03", "servicio": "20", "valor_declarado": "50", "observaciones": "corregido",
            "modo_bultos": "detallado",
            "bulto_tipo": ["PALLET"], "bulto_cantidad": ["2"], "bulto_alto": ["10"],
            "bulto_ancho": ["20"], "bulto_largo": ["30"], "bulto_peso": ["5.0"],
            "bulto_tipo_contenido": ["SECO"],
        })
        self.assertEqual(resp.status_code, 302)
        self.envio.refresh_from_db()
        self.assertEqual(self.envio.orden_transporte, "OT-2")
        self.assertEqual(self.envio.datos_courier["centro"], "03")
        self.assertEqual(self.envio.datos_courier["bultos"][0]["tipo"], "PALLET")


class EliminarEnvioViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        self.pedido = crear_pedido("2101", envio=self.envio)

    def test_no_admin_no_puede_eliminar(self):
        self.client.force_login(self.logi)
        self.client.post(f"/envios/{self.envio.pk}/eliminar/")
        self.assertTrue(EnvioCourier.objects.filter(pk=self.envio.pk).exists())

    def test_admin_elimina_y_pedido_queda_sin_envio(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/envios/{self.envio.pk}/eliminar/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.envio_id)


class RefrescarEstadoViewsTest(TestCase):
    """El ejecutivo también puede refrescar el estado-courier: individual de los envíos que ve,
    y el batch acotado a los suyos. Logística/Admin sobre todos."""

    def setUp(self):
        self.client = Client()
        self.ejec_obj = crear_ejecutivo(codigo_sap=10)
        self.ejec_obj_b = crear_ejecutivo(codigo_sap=20, nombre="Otro", email="otro@bioquimica.cl")
        self.dueno = crear_usuario("dueno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.envio_a = EnvioCourier.objects.create(courier=Courier.MOVEUP)   # del dueño (código 10)
        crear_pedido("3001", envio=self.envio_a, ejecutivo=self.ejec_obj)
        self.envio_b = EnvioCourier.objects.create(courier=Courier.MOVEUP)   # del ajeno (código 20)
        crear_pedido("3002", envio=self.envio_b, ejecutivo=self.ejec_obj_b)

    # --- individual (refrescar_estado_envio) ---
    @patch("envios.views.actualizar_estado_courier", return_value=True)
    def test_individual_ejecutivo_dueno_refresca(self, mock_act):
        self.client.force_login(self.dueno)
        resp = self.client.post(f"/envios/{self.envio_a.pk}/refrescar-estado/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(mock_act.called)

    @patch("envios.views.actualizar_estado_courier", return_value=True)
    def test_individual_ejecutivo_ajeno_no_refresca(self, mock_act):
        self.client.force_login(self.ajeno)
        self.client.post(f"/envios/{self.envio_a.pk}/refrescar-estado/")   # envío de otro
        self.assertFalse(mock_act.called)   # cortó por puede_ver_envio, no llamó a la API

    @patch("envios.views.actualizar_estado_courier", return_value=True)
    def test_individual_logistica_refresca_cualquiera(self, mock_act):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio_b.pk}/refrescar-estado/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(mock_act.called)

    # --- batch (refrescar_estados) ---
    @patch("envios.views.refrescar_estados_courier", return_value=1)
    def test_batch_ejecutivo_solo_los_suyos(self, mock_batch):
        self.client.force_login(self.dueno)
        resp = self.client.post("/envios/refrescar-estados/")
        self.assertEqual(resp.status_code, 204)
        pks = set(mock_batch.call_args[0][0].values_list("pk", flat=True))
        self.assertIn(self.envio_a.pk, pks)
        self.assertNotIn(self.envio_b.pk, pks)   # el ajeno NO entra

    @patch("envios.views.refrescar_estados_courier", return_value=2)
    def test_batch_logistica_todos(self, mock_batch):
        self.client.force_login(self.logi)
        resp = self.client.post("/envios/refrescar-estados/")
        self.assertEqual(resp.status_code, 204)
        pks = set(mock_batch.call_args[0][0].values_list("pk", flat=True))
        self.assertIn(self.envio_a.pk, pks)
        self.assertIn(self.envio_b.pk, pks)
