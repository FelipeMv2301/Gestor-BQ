import base64, io
from unittest.mock import patch
from pypdf import PdfWriter, PdfReader
from django.test import TestCase, RequestFactory, Client
from django.conf import settings
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos.tests.factories import crear_pedido, crear_usuario, crear_ejecutivo
from utils import Courier
from integraciones import chibra_client, seguimiento, starken_client
from .services import parsear_bultos, validar_pedidos_para_despacho, despachar_pedidos, _parsear_despacho_starken, anular_envio_courier, marcar_incidencia_envio
from .models import EnvioCourier
from .reportes import filas_reporte
from enviosIncidencias.models import EnvioIncidencia

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

    def test_departamento_remitente_siempre_vacio(self):
        # Bug real detectado 2026-08-18: un departamentoRemitente no vacío ("Sección 4 S-2", 13
        # caracteres) rompió el servidor de Starken con un HTTP 500 sin manejar — a diferencia de su
        # gemelo del destinatario, no tiene largo máximo documentado. Ese dato interno (sección de
        # bodega) no le sirve al courier para retirar (Til Til 2756 es un único andén) — se decidió
        # no mandarlo en absoluto, no buscarle otro campo dónde meterlo.
        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        capturado, fake_post = self._post_capturado({"codigoError": 0, "nroOrdenFlete": 222000004})

        with patch("integraciones.starken_client.requests.post", side_effect=fake_post):
            starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        self.assertEqual(capturado["payload"]["departamentoRemitente"], "")
        self.assertEqual(capturado["payload"]["direccionRemitente"], settings.STARKEN_DIRECCION_REMITENTE)

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

    def test_error_http_de_starken_muestra_status_y_detalle_no_generico(self):
        # Bug real detectado 2026-08-18: un HTTP 400/403/500 (la conexión SÍ llegó a Starken, pero
        # Starken respondió con un error) se mostraba con el mismo mensaje genérico de "no se pudo
        # conectar" que una falla de red real — escondiendo justo el detalle que hacía falta para
        # depurar (confirmado con curl/shell en el servidor: la conexión funcionaba perfecto).
        import requests

        def fake_post_400(url, json=None, timeout=None):
            class FakeResponse400:
                status_code = 400
                text = '{"code":400,"message":"Metodo no permitido"}'
                def raise_for_status(self):
                    raise requests.exceptions.HTTPError(response=self)
            return FakeResponse400()

        bultos = [{"cantidad": 1, "peso": 1.0, "alto": "1", "ancho": "1", "largo": "1", "tipo_contenido": ""}]
        with patch("integraciones.starken_client.requests.post", side_effect=fake_post_400):
            with self.assertRaises(ValueError) as ctx:
                starken_client.emitir_of([], bultos, self._destinatario(), {"servicio": "0"})

        mensaje = str(ctx.exception)
        self.assertIn("400", mensaje)
        self.assertIn("Metodo no permitido", mensaje)
        self.assertNotIn("no se pudo conectar", mensaje)


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
             patch("envios.services.notificar_pedidos_despacho") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.CHIBRA, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "OT-123")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(envio.datos_courier["bultos"], _bultos())  # el fix de hoy: bultos SÍ quedan guardados
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 1)  # un solo correo agrupado, no uno por pedido

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

    def test_notificacion_grupal_fallida_reporta_todos_los_pedidos(self):
        p1 = crear_pedido("2006", **self.aprobado)
        p2 = crear_pedido("2007", **self.aprobado)
        with patch("envios.services.chibra_client.documentar_envio", return_value={"numero_envio": "OT-789"}), \
             patch("envios.services.notificar_pedidos_despacho", side_effect=ValueError("SMTP caído")):
            envio, fallidas = despachar_pedidos([p1, p2], Courier.CHIBRA, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertIsNotNone(envio.pk)
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)  # el despacho quedó igual, solo falló el email
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(len(fallidas), 2)  # una tupla por pedido, mismo error, no una sola tupla para el grupo
        self.assertEqual({p for p, _ in fallidas}, {p1, p2})
        self.assertTrue(all("SMTP caído" in error for _, error in fallidas))

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
             patch("envios.services.notificar_pedidos_despacho") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.MOVEUP, [], destinatario, _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "555")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 1)  # un solo correo agrupado, no uno por pedido

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
             patch("envios.services.notificar_pedidos_despacho") as mock_notificar:
            envio, fallidas = despachar_pedidos([p1, p2], Courier.STARKEN, _bultos(), _destinatario(), _datos_courier(), self.usuario)

        self.assertEqual(envio.orden_transporte, "222607751")
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)
        self.assertEqual(envio.datos_courier["bultos"], _bultos())
        self.assertEqual(fallidas, [])
        p1.refresh_from_db(); p2.refresh_from_db()
        self.assertEqual(p1.envio_id, envio.id)
        self.assertEqual(p2.envio_id, envio.id)
        self.assertEqual(mock_notificar.call_count, 1)  # un solo correo agrupado, no uno por pedido

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


class AnularEnvioCourierTest(TestCase):
    def test_starken_ok_marca_envio_anulado(self):
        envio = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="245256402",
                                             estado=EnvioCourier.Estado.DESPACHADO)
        with patch("envios.services.starken_client.anular_of") as mock_anular:
            anular_envio_courier(envio)

        mock_anular.assert_called_once_with("245256402")
        envio.refresh_from_db()
        self.assertEqual(envio.estado, EnvioCourier.Estado.ANULADO)

    def test_courier_sin_soporte_no_llama_a_nadie_y_no_cambia_estado(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-1",
                                             estado=EnvioCourier.Estado.DESPACHADO)
        with self.assertRaises(ValueError):
            anular_envio_courier(envio)
        envio.refresh_from_db()
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)

    def test_sin_orden_transporte_falla_antes_de_llamar_a_starken(self):
        envio = EnvioCourier.objects.create(courier=Courier.STARKEN)
        with patch("envios.services.starken_client.anular_of") as mock_anular:
            with self.assertRaises(ValueError):
                anular_envio_courier(envio)
        self.assertFalse(mock_anular.called)

    def test_error_de_starken_no_marca_como_anulado(self):
        envio = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="245256402",
                                             estado=EnvioCourier.Estado.DESPACHADO)
        with patch("envios.services.starken_client.anular_of", side_effect=ValueError("[!] Error: no se pudo")):
            with self.assertRaises(ValueError):
                anular_envio_courier(envio)
        envio.refresh_from_db()
        self.assertEqual(envio.estado, EnvioCourier.Estado.DESPACHADO)


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


# Chibra ya devuelve la etiqueta en documentar_envio, pero esa llamada no se puede repetir (crea el
# envío de nuevo) — obtener_etiqueta usa etiquetarService con ETIQUETAR="R" para volver a pedirla.
class ObtenerEtiquetaChibraTest(TestCase):
    def _fake_response(self, resultado="OK", etiqueta_b64=None, mensaje="Etiqueta creada con éxito"):
        cuerpo = {"resultado": resultado, "mensaje": mensaje}
        if etiqueta_b64:
            cuerpo["etiqueta"] = etiqueta_b64

        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return [{"respuestaEtiquetar": cuerpo}]
        return FakeResponse()

    def test_decodifica_la_etiqueta_en_base64(self):
        etiqueta_b64 = base64.b64encode(b"%PDF-fake").decode()
        with patch("integraciones.chibra_client.requests.post",
                    return_value=self._fake_response(etiqueta_b64=etiqueta_b64)) as mock_post:
            resultado = chibra_client.obtener_etiqueta("02", "999903204829")

        self.assertEqual(resultado, b"%PDF-fake")
        mock_post.assert_called_once_with(
            f"{settings.CHIBRA_BASE_URL}/gts/seam/resource/restv1/auth/etiquetarService/etiquetar",
            auth=(settings.CHIBRA_USER, settings.CHIBRA_PASSWORD),
            json={
                "ETIQUETAS": {
                    "VERSION": "5",
                    "ETIQUETA": [{
                        "CLIENTE": settings.CHIBRA_CLIENTE_REMITENTE,
                        "CENTRO": "02",
                        "EXPEDICION": "999903204829",
                        "ETIQUETAR": "R",
                        "FORMATO": "PDF",
                    }]
                }
            },
            timeout=30,
        )

    def test_resultado_error_lanza_excepcion(self):
        with patch("integraciones.chibra_client.requests.post",
                    return_value=self._fake_response(
                        resultado="ERROR", mensaje="La expedición que ha intentado etiquetar no existe")):
            with self.assertRaises(ValueError):
                chibra_client.obtener_etiqueta("02", "000000000000")


# Etracking: seguimiento MASIVO de Starken (1 sola llamada para varias OF), para el botón
# "Actualizar estados" en lote. Esquema de auth propio (api-key/cli-rut/password).
class ConsultarEstadosBatchStarkenTest(TestCase):
    def _fake_response(self, filas):
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"listaResumenRedestinacion": {"ordenFlete": filas}}
        return FakeResponse()

    def test_devuelve_solo_las_ofs_con_codigo_salida_1(self):
        filas = [
            {"codigoSalida": 1, "numeroOrdenFlete": 222582312, "estadoOrdenFlete": "DEVUELTO AL CLIENTE"},
            {"codigoSalida": 0, "numeroOrdenFlete": 999999999, "estadoOrdenFlete": "NO DEBERIA APARECER"},
        ]
        with patch("integraciones.starken_client.requests.post",
                    return_value=self._fake_response(filas)) as mock_post:
            resultado = starken_client.consultar_estados_batch(["222582312", "999999999"])

        self.assertEqual(resultado, {"222582312": "DEVUELTO AL CLIENTE"})
        mock_post.assert_called_once_with(
            settings.STARKEN_ETRACKING_URL,
            headers={
                "api-key": settings.STARKEN_ETRACKING_API_KEY,
                "cli-rut": settings.STARKEN_ETRACKING_CLI_RUT,
                "password": settings.STARKEN_ETRACKING_PASSWORD,
            },
            json={
                "tracking": [
                    {"numeroDocumento": "", "numeroOrdenFlete": "222582312", "tipoDocumento": ""},
                    {"numeroDocumento": "", "numeroOrdenFlete": "999999999", "tipoDocumento": ""},
                ],
                "rutEmpresa": settings.STARKEN_RUT_EMPRESA_EMISORA,
            },
            timeout=30,
        )

    def test_sin_filas_devuelve_diccionario_vacio(self):
        with patch("integraciones.starken_client.requests.post", return_value=self._fake_response([])):
            resultado = starken_client.consultar_estados_batch(["222582312"])
        self.assertEqual(resultado, {})


class RefrescarEstadoStarkenBatchTest(TestCase):
    def test_actualiza_solo_las_ofs_que_starken_devolvio(self):
        con_estado = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="111")
        sin_novedad = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="222")

        with patch("integraciones.seguimiento.starken_client.consultar_estados_batch",
                    return_value={"111": "EN TRANSITO"}) as mock_batch:
            actualizados = seguimiento._refrescar_estado_starken_batch([con_estado, sin_novedad])

        self.assertEqual(actualizados, 1)
        mock_batch.assert_called_once_with(["111", "222"])
        con_estado.refresh_from_db()
        sin_novedad.refresh_from_db()
        self.assertEqual(con_estado.estado_courier, "EN TRANSITO")
        self.assertIsNotNone(con_estado.estado_courier_actualizado)
        self.assertEqual(sin_novedad.estado_courier, "")   # Starken no la devolvió: no se pisa
        self.assertIsNone(sin_novedad.estado_courier_actualizado)

    def test_envios_sin_orden_transporte_se_excluyen_de_la_llamada(self):
        sin_ot = EnvioCourier.objects.create(courier=Courier.STARKEN)
        con_ot = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="333")

        with patch("integraciones.seguimiento.starken_client.consultar_estados_batch",
                    return_value={"333": "ENTREGADO"}) as mock_batch:
            actualizados = seguimiento._refrescar_estado_starken_batch([sin_ot, con_ot])

        self.assertEqual(actualizados, 1)
        mock_batch.assert_called_once_with(["333"])

    def test_lista_vacia_no_llama_a_la_api(self):
        with patch("integraciones.seguimiento.starken_client.consultar_estados_batch") as mock_batch:
            actualizados = seguimiento._refrescar_estado_starken_batch([])
        self.assertEqual(actualizados, 0)
        self.assertFalse(mock_batch.called)


# Anulación de OF: dos llamadas (login → token JWT, luego anular con ese Bearer). El token no se
# reusa entre llamadas — cada anulación pide uno nuevo (así lo exige el manual de Starken).
class AnularOfStarkenTest(TestCase):
    def _fake_response(self, payload):
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return payload
        return FakeResponse()

    def test_anula_ok(self):
        respuestas = [
            self._fake_response({"token": "jwt-falso"}),
            self._fake_response({"data": [{"numeroOrden": 245256402, "mensaje": "OK", "estado": "OK"}],
                                  "ordersProcessed": 1, "status": 200}),
        ]
        with patch("integraciones.starken_client.requests.post", side_effect=respuestas) as mock_post:
            starken_client.anular_of(245256402)   # no lanza

        login_call, anular_call = mock_post.call_args_list
        self.assertEqual(login_call.args[0], settings.STARKEN_ANULACION_LOGIN_URL)
        self.assertEqual(login_call.kwargs["json"]["run"], settings.STARKEN_ANULACION_RUN)
        self.assertEqual(anular_call.args[0], settings.STARKEN_ANULACION_URL)
        self.assertEqual(anular_call.kwargs["headers"], {"Authorization": "Bearer jwt-falso"})
        self.assertEqual(anular_call.kwargs["json"], {"numerosOrden": [245256402]})

    def test_starken_rechaza_con_estado_no_ok_lanza_con_motivo(self):
        respuestas = [
            self._fake_response({"token": "jwt-falso"}),
            self._fake_response({"data": [{"numeroOrden": 245256402,
                                            "mensaje": "Orden de flete no corresponde al cliente.",
                                            "estado": "NO_OK"}]}),
        ]
        with patch("integraciones.starken_client.requests.post", side_effect=respuestas):
            with self.assertRaisesMessage(ValueError, "Orden de flete no corresponde al cliente."):
                starken_client.anular_of(245256402)

    def test_sin_token_de_login_lanza_error(self):
        with patch("integraciones.starken_client.requests.post",
                    return_value=self._fake_response({})):
            with self.assertRaises(ValueError):
                starken_client.anular_of(245256402)


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
    # el courier no tiene ese tipo registrado. "evidencia_entrega" hoy no está registrado para
    # ningún courier (Starken la deja comentada a la espera de HU-ST4.3).
    def test_courier_sin_ese_documento_muestra_error(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio_chibra.pk}/documento/evidencia_entrega/")
        self.assertRedirects(resp, f"/envios/{self.envio_chibra.pk}/")

    # Chibra usa etiquetarService (obtener_etiqueta), que además del orden_transporte necesita el
    # centro con el que se despachó — vive en datos_courier, no en un campo propio de EnvioCourier.
    def test_descarga_etiqueta_chibra_usa_centro_de_datos_courier(self):
        self.envio_chibra.datos_courier = {"centro": "02"}
        self.envio_chibra.save(update_fields=["datos_courier"])
        self.client.force_login(self.logi)
        with patch("integraciones.documentos.chibra_client.obtener_etiqueta",
                    return_value=b"%PDF-fake") as mock_obtener:
            resp = self.client.get(f"/envios/{self.envio_chibra.pk}/documento/etiqueta/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"%PDF-fake")
        mock_obtener.assert_called_once_with("02", "OT-1")

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

    def test_detalle_envio_chibra_muestra_documentos_disponibles(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio_chibra.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["documentos"], [("etiqueta", "Etiqueta de envío")])


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


class AnularEnvioViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.envio_starken = EnvioCourier.objects.create(
            courier=Courier.STARKEN, orden_transporte="245256402", estado=EnvioCourier.Estado.DESPACHADO)
        self.envio_chibra = EnvioCourier.objects.create(
            courier=Courier.CHIBRA, orden_transporte="OT-1", estado=EnvioCourier.Estado.DESPACHADO)

    def test_no_logistica_no_puede_anular(self):
        self.client.force_login(self.ejec)
        with patch("envios.views.anular_envio_courier") as mock_anular:
            resp = self.client.post(f"/envios/{self.envio_starken.pk}/anular/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(mock_anular.called)

    def test_logistica_anula_starken_ok(self):
        self.client.force_login(self.logi)
        with patch("envios.views.anular_envio_courier") as mock_anular:
            resp = self.client.post(f"/envios/{self.envio_starken.pk}/anular/")
        self.assertEqual(resp.status_code, 302)
        mock_anular.assert_called_once_with(self.envio_starken)

    # No mockea anular_envio_courier: ejercita el ValueError real cuando el courier no está en
    # ANULAR_COURIER (Chibra) — debe mostrar el error en pantalla, no un 500.
    def test_courier_sin_soporte_muestra_error_sin_reventar(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio_chibra.pk}/anular/")
        self.assertRedirects(resp, f"/envios/{self.envio_chibra.pk}/")
        self.envio_chibra.refresh_from_db()
        self.assertEqual(self.envio_chibra.estado, EnvioCourier.Estado.DESPACHADO)

    def test_error_de_starken_se_muestra_y_no_crashea(self):
        self.client.force_login(self.logi)
        with patch("envios.views.anular_envio_courier", side_effect=ValueError("[!] Error: OF con movimientos")):
            resp = self.client.post(f"/envios/{self.envio_starken.pk}/anular/")
        self.assertRedirects(resp, f"/envios/{self.envio_starken.pk}/")

    def test_detalle_envio_starken_ofrece_anular_chibra_no(self):
        self.client.force_login(self.logi)
        resp_starken = self.client.get(f"/envios/{self.envio_starken.pk}/")
        resp_chibra = self.client.get(f"/envios/{self.envio_chibra.pk}/")
        self.assertTrue(resp_starken.context["puede_anular"])
        self.assertFalse(resp_chibra.context["puede_anular"])


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

    # El filtro del batch ya no está hardcodeado a MOVEUP — cualquier courier registrado en
    # REFRESCAR_ESTADO_BATCH entra (hoy MoveUP y Starken). Chibra no está registrado, no debe entrar.
    @patch("envios.views.refrescar_estados_courier", return_value=3)
    def test_batch_incluye_starken_pero_no_chibra(self, mock_batch):
        envio_starken = EnvioCourier.objects.create(courier=Courier.STARKEN)
        envio_chibra = EnvioCourier.objects.create(courier=Courier.CHIBRA)
        self.client.force_login(self.logi)
        resp = self.client.post("/envios/refrescar-estados/")
        self.assertEqual(resp.status_code, 204)
        pks = set(mock_batch.call_args[0][0].values_list("pk", flat=True))
        self.assertIn(envio_starken.pk, pks)
        self.assertNotIn(envio_chibra.pk, pks)


class MarcarIncidenciaEnvioTest(TestCase):
    """envios/services.py::marcar_incidencia_envio — archiva el envío (EnvioIncidencia) y libera los
    pedidos asociados vía el SET_NULL de Pedido.envio."""

    def setUp(self):
        self.logi = crear_usuario("logi_inc@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_usuario("ejec_inc@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-INC-1")
        self.p1 = crear_pedido("8001", envio=self.envio, rut="76563320-6", razon_social="Bioquimica CL",
                                estado_notificacion=Pedido.EstadoNotificacion.NOTIFICADO)
        self.p2 = crear_pedido("8002", envio=self.envio, rut="76563320-6",
                                estado_notificacion=Pedido.EstadoNotificacion.NOTIFICADO)

    def test_archiva_libera_pedidos_y_resetea_notificacion(self):
        incidencia = marcar_incidencia_envio(self.envio, "Paquete extraviado", self.logi)

        self.assertFalse(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.assertEqual(incidencia.courier, Courier.CHIBRA)
        self.assertEqual(incidencia.orden_transporte, "OT-INC-1")
        self.assertEqual(incidencia.motivo, "Paquete extraviado")
        self.assertEqual(incidencia.registrado_por, self.logi)
        self.assertEqual(len(incidencia.pedidos_incluidos), 2)
        self.assertEqual({p["num_pedido"] for p in incidencia.pedidos_incluidos}, {"8001", "8002"})

        self.p1.refresh_from_db(); self.p2.refresh_from_db()
        self.assertIsNone(self.p1.envio_id)
        self.assertIsNone(self.p2.envio_id)
        self.assertEqual(self.p1.estado_notificacion, Pedido.EstadoNotificacion.NO_NOTIFICADO)
        self.assertEqual(self.p1.estado_seguimiento[0], "Recién Ingresado")

    def test_snapshot_incluye_datos_del_envio(self):
        envio = EnvioCourier.objects.create(
            courier=Courier.CHIBRA, orden_transporte="OT-INC-2",
            datos_courier={"centro": "02", "servicio": "10"},
        )
        incidencia = marcar_incidencia_envio(envio, "x", self.logi)
        self.assertEqual(incidencia.snapshot["datos_courier"], {"centro": "02", "servicio": "10"})
        self.assertEqual(incidencia.snapshot["orden_transporte"], "OT-INC-2")

    def test_ejecutivo_no_puede(self):
        with self.assertRaises(PermissionError):
            marcar_incidencia_envio(self.envio, "x", self.ejec)
        self.assertTrue(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.assertEqual(EnvioIncidencia.objects.count(), 0)

    def test_envio_sin_pedidos_igual_se_puede_archivar(self):
        envio_vacio = EnvioCourier.objects.create(courier=Courier.MOVEUP)
        incidencia = marcar_incidencia_envio(envio_vacio, "x", self.logi)
        self.assertEqual(incidencia.pedidos_incluidos, [])
        self.assertFalse(EnvioCourier.objects.filter(pk=envio_vacio.pk).exists())


class MarcarIncidenciaVistaTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi_inc2@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_usuario("ejec_inc2@bioquimica.cl", Rol.EJECUTIVO)
        self.envio = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-INC-3")
        self.pedido = crear_pedido("8003", envio=self.envio)

    def test_logistica_reporta_incidencia_y_redirige_al_listado(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio.pk}/incidencia/", {"motivo": "Paquete dañado"})
        self.assertRedirects(resp, "/envios/")
        self.assertFalse(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.assertEqual(EnvioIncidencia.objects.count(), 1)
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.envio_id)

    def test_sin_motivo_no_hace_nada_y_vuelve_al_detalle(self):
        self.client.force_login(self.logi)
        resp = self.client.post(f"/envios/{self.envio.pk}/incidencia/", {"motivo": "   "})
        self.assertRedirects(resp, f"/envios/{self.envio.pk}/")
        self.assertTrue(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.assertEqual(EnvioIncidencia.objects.count(), 0)

    def test_ejecutivo_no_puede(self):
        self.client.force_login(self.ejec)
        resp = self.client.post(f"/envios/{self.envio.pk}/incidencia/", {"motivo": "x"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(EnvioCourier.objects.filter(pk=self.envio.pk).exists())
        self.assertEqual(EnvioIncidencia.objects.count(), 0)

    def test_get_no_permitido(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio.pk}/incidencia/")
        self.assertEqual(resp.status_code, 405)

    def test_boton_visible_en_detalle_para_cualquier_courier(self):
        self.client.force_login(self.logi)
        resp = self.client.get(f"/envios/{self.envio.pk}/")
        contenido = resp.content.decode()
        self.assertIn("Reportar incidencia", contenido)
        self.assertNotIn("Marcar Entregado", contenido)
        self.assertNotIn("Marcar Error", contenido)

    def test_ejecutivo_no_ve_el_boton(self):
        self.client.force_login(self.ejec)
        resp = self.client.get(f"/envios/{self.envio.pk}/")
        self.assertNotIn("Reportar incidencia", resp.content.decode())


class ListadoIncidenciasTest(TestCase):
    """envios/views.py::lista_incidencias / mis_incidencias — pedidos_incluidos guarda ejecutivo_id
    (snapshot, no FK) para que el Ejecutivo pueda filtrar las suyas incluso después de que el pedido
    original haya sido liberado/reasignado."""

    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi_li@bioquimica.cl", Rol.LOGISTICA)
        self.ejec_obj = crear_ejecutivo(codigo_sap=30)
        self.dueno = crear_usuario("dueno_li@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=30)
        self.ajeno_obj = crear_ejecutivo(codigo_sap=40, nombre="Otro", email="otro_li@bioquimica.cl")
        self.ajeno = crear_usuario("ajeno_li@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=40)

        envio_dueno = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-DUENO")
        crear_pedido("9101", envio=envio_dueno, ejecutivo=self.ejec_obj)
        self.incidencia_dueno = marcar_incidencia_envio(envio_dueno, "Extraviado", self.logi)

        envio_ajeno = EnvioCourier.objects.create(courier=Courier.STARKEN, orden_transporte="OT-AJENO")
        crear_pedido("9102", envio=envio_ajeno, ejecutivo=self.ajeno_obj)
        self.incidencia_ajeno = marcar_incidencia_envio(envio_ajeno, "Dañado", self.logi)

    def test_logistica_ve_listado_completo(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/envios/incidencias/")
        self.assertEqual(resp.status_code, 200)
        contenido = resp.content.decode()
        self.assertIn("OT-DUENO", contenido)
        self.assertIn("OT-AJENO", contenido)

    def test_ejecutivo_ve_solo_las_que_incluyen_pedidos_suyos(self):
        self.client.force_login(self.dueno)
        resp = self.client.get("/envios/mis-incidencias/")
        contenido = resp.content.decode()
        self.assertIn("OT-DUENO", contenido)
        self.assertNotIn("OT-AJENO", contenido)

    def test_ejecutivo_ajeno_no_ve_la_de_otro(self):
        self.client.force_login(self.ajeno)
        resp = self.client.get("/envios/mis-incidencias/")
        contenido = resp.content.decode()
        self.assertIn("OT-AJENO", contenido)
        self.assertNotIn("OT-DUENO", contenido)

    def test_ejecutivo_no_puede_ver_listado_completo(self):
        self.client.force_login(self.dueno)
        resp = self.client.get("/envios/incidencias/")
        self.assertEqual(resp.status_code, 302)

    def test_logistica_no_tiene_mis_incidencias(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/envios/mis-incidencias/")
        self.assertEqual(resp.status_code, 302)

    def test_sin_incidencias_muestra_mensaje_vacio(self):
        EnvioIncidencia.objects.all().delete()
        self.client.force_login(self.logi)
        resp = self.client.get("/envios/incidencias/")
        self.assertIn("No hay incidencias registradas.", resp.content.decode())


class ReporteEjecutivosActivosTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi_rep@bioquimica.cl", Rol.LOGISTICA)
        self.ejec_activo = crear_ejecutivo(codigo_sap=50, nombre="Activo", email="activo_rep@bioquimica.cl", activo=True)
        self.ejec_inactivo = crear_ejecutivo(codigo_sap=51, nombre="Inactivo", email="inactivo_rep@bioquimica.cl", activo=False)

    def test_form_solo_lista_ejecutivos_activos(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/envios/reporte/")
        contenido = resp.content.decode()
        self.assertIn("Activo", contenido)
        self.assertNotIn("Inactivo", contenido)


class ReporteIncidenciasTest(TestCase):
    """envios/reportes.py::filas_reporte con incluir_incidencias — suma filas armadas desde
    EnvioIncidencia (envío ya borrado, todo sale del snapshot)."""

    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi_repinc@bioquimica.cl", Rol.LOGISTICA)
        self.ejec = crear_ejecutivo(codigo_sap=60, nombre="Repinc", email="repinc@bioquimica.cl")

    def test_checkbox_incidencias_presente_en_form(self):
        self.client.force_login(self.logi)
        resp = self.client.get("/envios/reporte/")
        self.assertIn('name="incidencias"', resp.content.decode())

    def test_sin_incidencias_por_defecto(self):
        envio = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-NORMAL")
        crear_pedido("6001", envio=envio, ejecutivo=self.ejec)
        envio_incidencia = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-INC")
        crear_pedido("6002", envio=envio_incidencia, ejecutivo=self.ejec)
        marcar_incidencia_envio(envio_incidencia, "Extraviado", self.logi)

        filas = filas_reporte(None, None, [], [], self.logi, incluir_incidencias=False)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["ot"], "OT-NORMAL")

    def test_con_incidencias_suma_la_fila_con_datos_del_snapshot(self):
        envio_incidencia = EnvioCourier.objects.create(
            courier=Courier.STARKEN, orden_transporte="OT-INC2",
            datos_courier={"bultos": [{"cantidad": 3}], "valor_declarado": "7000"},
        )
        crear_pedido("6004", envio=envio_incidencia, ejecutivo=self.ejec)
        marcar_incidencia_envio(envio_incidencia, "Dañado en tránsito", self.logi)

        filas = filas_reporte(None, None, [], [], self.logi, incluir_incidencias=True)
        self.assertEqual(len(filas), 1)
        fila = filas[0]
        self.assertEqual(fila["estado_courier"], "INCIDENCIA: Dañado en tránsito")
        self.assertEqual(fila["n_bultos"], 3)
        self.assertEqual(fila["valor_declarado"], 7000)
        self.assertIn("6004", fila["pedidos"])
        self.assertIn("Repinc", fila["ejecutivo"])

    def test_reporte_ver_respeta_el_checkbox(self):
        envio_incidencia = EnvioCourier.objects.create(courier=Courier.CHIBRA, orden_transporte="OT-INC3")
        crear_pedido("6005", envio=envio_incidencia, ejecutivo=self.ejec)
        marcar_incidencia_envio(envio_incidencia, "x", self.logi)

        self.client.force_login(self.logi)
        resp_sin = self.client.get("/envios/reporte/ver/")
        self.assertNotIn("OT-INC3", resp_sin.content.decode())

        resp_con = self.client.get("/envios/reporte/ver/?incidencias=on")
        self.assertIn("OT-INC3", resp_con.content.decode())
