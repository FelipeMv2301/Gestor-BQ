"""Render de pedidos/views/despacho.py::armar_despacho — nadie lo probaba por courier hasta ahora.
assertContains ya falla si el template tira 500 (typo de {% %}, variable mal armada, etc.)."""
from django.test import TestCase, Client
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from utils import Courier
from .factories import crear_usuario, crear_pedido

Rol = PerfilUsuario.Rol


class ArmarDespachoTemplateTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)

    def _pedido_aprobado(self, num, courier):
        return crear_pedido(
            num, estado_comercial=Pedido.EstadoComercial.APROBADO, courier=courier, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_render_starken(self):
        p = self._pedido_aprobado("7001", Courier.STARKEN)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "starken_calle")
        self.assertContains(resp, "codigo_agencia_destino")
        self.assertContains(resp, "doc_tipo")
        self.assertContains(resp, 'name="bulto_tipo" value="CAJA"')

    def test_render_chibra_sigue_funcionando(self):
        p = self._pedido_aprobado("7002", Courier.CHIBRA)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "destinatario_direccion")

    def test_render_moveup_sigue_funcionando(self):
        p = self._pedido_aprobado("7003", Courier.MOVEUP)
        self.client.force_login(self.logi)
        resp = self.client.get(f"/pedidos/armar-despacho/?ids={p.pk}")
        self.assertContains(resp, "moveup_calle")


class ArmarDespachoNoPierdeDatosAlFallarTest(TestCase):
    """El fix real: antes, cualquier error en el POST hacía redirect (302) y el navegador perdía
    todo lo tipeado al recargar. Ahora debe quedarse en la misma pantalla (200) con los valores
    ya escritos precargados en los inputs — se prueba con un envío que falta un dato a propósito."""

    def setUp(self):
        self.client = Client()
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)

    def _pedido_aprobado(self, num, courier):
        return crear_pedido(
            num, estado_comercial=Pedido.EstadoComercial.APROBADO, courier=courier, rut="11111111-1",
            telefono_contacto="+56911112222", direccion_calle="Av. Providencia 123", direccion_comuna="Providencia",
        )

    def test_starken_sin_nombre_conserva_direccion_y_bultos_tipeados(self):
        p = self._pedido_aprobado("7101", Courier.STARKEN)
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/armar-despacho/?ids={p.pk}", {
            "ids": str(p.pk),
            "destinatario_nombre": "",  # a propósito vacío: dispara el ValueError del parser
            "destinatario_rut": "11111111-1", "destinatario_telefono": "+56911112222",
            "destinatario_email": "cliente@x.cl", "destinatario_comuna": "Ñuñoa Tipeada",
            "starken_calle": "Calle Tipeada A Mano", "starken_numero": "999", "starken_depto": "",
            "valor_declarado": "5000", "contenido": "REACTIVOS DE LABORATORIO", "observaciones": "",
            "modo_bultos": "detallado", "bulto_tipo": ["CAJA"],  # input hidden real del template Starken
            "bulto_cantidad": ["3"], "bulto_alto": ["7"], "bulto_ancho": ["8"], "bulto_largo": ["9"],
            "bulto_peso": ["1.5"], "bulto_tipo_contenido": [""],
        })
        self.assertEqual(resp.status_code, 200)  # ya no hace redirect: se queda en la misma pantalla
        self.assertContains(resp, "Faltan datos para Starken")
        self.assertContains(resp, "Calle Tipeada A Mano")
        self.assertContains(resp, "Ñuñoa Tipeada")
        self.assertContains(resp, 'value="999"')
        self.assertContains(resp, 'value="REACTIVOS DE LABORATORIO"')
        self.assertContains(resp, 'value="7"')   # alto del bulto tipeado, no vacío

    def test_starken_conserva_destinatario_editado_al_fallar(self):
        # El bloque "Destinatario" es compartido por los 4 couriers (armar_despacho.html), no vive en
        # el partial de Starken — bug real encontrado 2026-08-18: precargaba siempre desde pedidos.0,
        # nunca desde el POST, así que si Logística editaba nombre/RUT/teléfono/email antes de fallar
        # el envío, esos cambios se perdían (el resto del formulario sí los conservaba desde antes).
        p = self._pedido_aprobado("7104", Courier.STARKEN)  # rut de fábrica: 11111111-1
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/armar-despacho/?ids={p.pk}", {
            "ids": str(p.pk),
            "destinatario_nombre": "Cliente Editado A Mano", "destinatario_rut": "8765432-K",
            "destinatario_telefono": "+56999998888", "destinatario_email": "editado@x.cl",
            "destinatario_comuna": "Providencia",
            "starken_calle": "", "starken_numero": "100", "starken_depto": "",  # calle vacía: dispara el ValueError
            "valor_declarado": "0", "contenido": "MERCADERIA", "observaciones": "",
            "bulto_tipo": ["CAJA"], "bulto_cantidad": ["1"], "bulto_alto": ["1"], "bulto_ancho": ["1"],
            "bulto_largo": ["1"], "bulto_peso": ["1"], "bulto_tipo_contenido": [""],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Faltan datos para Starken")
        self.assertContains(resp, 'value="Cliente Editado A Mano"')
        self.assertContains(resp, 'value="8765432-K"')
        self.assertContains(resp, 'value="+56999998888"')
        self.assertContains(resp, 'value="editado@x.cl"')

    def test_chibra_con_rut_invalido_conserva_bultos_y_documento_tipeados(self):
        p = self._pedido_aprobado("7102", Courier.CHIBRA)
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/armar-despacho/?ids={p.pk}", {
            "ids": str(p.pk),
            "destinatario_nombre": "Juan Pérez", "destinatario_rut": "11111111-9",  # DV incorrecto: falla en chibra_client
            "destinatario_telefono": "+56911112222", "destinatario_email": "cliente@x.cl",
            "destinatario_direccion": "Dirección Tipeada 456", "destinatario_comuna": "Providencia",
            "centro": "03", "servicio": "10", "valor_declarado": "0", "observaciones": "Frágil, avisar antes",
            "modo_bultos": "detallado",
            "bulto_tipo": ["PALLET"], "bulto_cantidad": ["2"], "bulto_alto": ["10"], "bulto_ancho": ["20"],
            "bulto_largo": ["30"], "bulto_peso": ["4.5"], "bulto_tipo_contenido": ["REFRIGERADO"],
            "doc_tipo": ["CED"], "doc_referencia": ["REF-TIPEADA-123"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dirección Tipeada 456")
        self.assertContains(resp, "Frágil, avisar antes")
        self.assertContains(resp, "REF-TIPEADA-123")
        self.assertContains(resp, 'value="30"')   # largo del bulto tipeado
        self.assertContains(resp, 'value="03" selected')  # centro elegido se mantiene marcado

    def test_moveup_sin_numero_conserva_calle_y_valor_tipeados(self):
        p = self._pedido_aprobado("7103", Courier.MOVEUP)
        self.client.force_login(self.logi)
        resp = self.client.post(f"/pedidos/armar-despacho/?ids={p.pk}", {
            "ids": str(p.pk),
            "destinatario_nombre": "Juan Pérez", "destinatario_rut": "11111111-1",
            "destinatario_telefono": "+56911112222", "destinatario_email": "cliente@x.cl",
            "moveup_calle": "Calle MoveUP Tipeada", "moveup_numero": "",  # vacío: dispara el ValueError
            "destinatario_comuna": "Providencia", "package_size": "1", "cantidad": "2",
            "valor_declarado": "12345", "observaciones": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Faltan datos para MoveUP")
        self.assertContains(resp, "Calle MoveUP Tipeada")
        self.assertContains(resp, 'value="12345"')
        self.assertContains(resp, 'value="2"')
