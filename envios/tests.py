from unittest.mock import patch
from django.test import TestCase, RequestFactory, Client
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos.tests.factories import crear_pedido, crear_usuario
from utils import Courier
from .services import parsear_bultos, validar_pedidos_para_despacho, despachar_pedidos
from .models import EnvioCourier

Rol = PerfilUsuario.Rol


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
