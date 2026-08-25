from django.test import TestCase
from cuentas.models import PerfilUsuario
from pedidos.models import Pedido
from pedidos import permisos
from .factories import crear_usuario, crear_ejecutivo, crear_pedido

Rol = PerfilUsuario.Rol
EC = Pedido.EstadoComercial
EN = Pedido.EstadoNotificacion


class PermisosTest(TestCase):
    def setUp(self):
        self.ejec = crear_ejecutivo(codigo_sap=10)
        self.pedido = crear_pedido(ejecutivo=self.ejec, estado_comercial=EC.PENDIENTE)

        self.dueno = crear_usuario("dueno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.ajeno = crear_usuario("ajeno@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=20)
        self.logi = crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA)
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.sin_rol = crear_usuario("nuevo@bioquimica.cl", None)

    # --- obtener_rol / responsable ---
    def test_obtener_rol(self):
        self.assertEqual(permisos.obtener_rol(self.dueno), Rol.EJECUTIVO)
        self.assertIsNone(permisos.obtener_rol(self.sin_rol))

    def test_responsable_del_pedido(self):
        self.assertTrue(permisos.responsable_del_pedido(self.dueno, self.pedido))
        self.assertFalse(permisos.responsable_del_pedido(self.ajeno, self.pedido))

    # --- rechazar: Admin siempre; ejecutivo dueño hasta que se despache a courier ---
    def test_rechazar_admin_y_dueno_sin_despachar(self):
        self.assertTrue(permisos.puede_rechazar(self.admin, self.pedido))
        self.assertTrue(permisos.puede_rechazar(self.dueno, self.pedido))
        self.assertFalse(permisos.puede_rechazar(self.ajeno, self.pedido))
        self.assertFalse(permisos.puede_rechazar(self.logi, self.pedido))

    def test_dueno_no_puede_rechazar_tras_despachar(self):
        self.pedido.envio_id = 999  # simula ya despachado a courier
        self.assertFalse(permisos.puede_rechazar(self.dueno, self.pedido))
        self.assertTrue(permisos.puede_rechazar(self.admin, self.pedido))  # Admin sin restricción

    # --- reingresar: Admin siempre; Ejecutivo solo los suyos ---
    def test_puede_reingresar(self):
        from pedidos import services
        from pedidosRechazados.models import PedidoRechazado
        # anular el pedido (dueño = ejec código 10) → archiva con snapshot["ejecutivo"] = ejec.pk
        services.rechazar_pedido(self.pedido, "test", self.admin)
        rech = PedidoRechazado.objects.get(num_pedido=self.pedido.num_pedido)
        self.assertTrue(permisos.puede_reingresar(self.admin, rech))    # admin, cualquiera
        self.assertTrue(permisos.puede_reingresar(self.dueno, rech))    # ejecutivo dueño
        self.assertFalse(permisos.puede_reingresar(self.ajeno, rech))   # otro ejecutivo
        self.assertFalse(permisos.puede_reingresar(self.logi, rech))    # logística no

    # --- editar por rol: ejecutivo hasta despachar (envio_id), logística hasta notificar ---
    def test_editar_segun_estado(self):
        self.assertTrue(permisos.puede_editar(self.dueno, self.pedido))   # sin envío, dueño
        self.assertTrue(permisos.puede_editar(self.logi, self.pedido))    # logística también, en paralelo
        self.pedido.envio_id = 999  # simula ya despachado a courier
        self.assertFalse(permisos.puede_editar(self.dueno, self.pedido))  # ejecutivo ya no puede
        self.assertTrue(permisos.puede_editar(self.logi, self.pedido))    # logística sigue pudiendo

    def test_notificado_bloquea_edicion_salvo_admin(self):
        self.pedido.estado_comercial = EC.APROBADO
        self.pedido.estado_notificacion = EN.NOTIFICADO
        self.assertFalse(permisos.puede_editar(self.logi, self.pedido))
        self.assertTrue(permisos.puede_editar(self.admin, self.pedido))

    # --- duplicar: Logística/Admin, solo si ya se despachó al menos una vez (envio_id) ---
    def test_puede_duplicar_pedido(self):
        self.assertFalse(permisos.puede_duplicar_pedido(self.logi, self.pedido))    # sin envío todavía
        self.assertFalse(permisos.puede_duplicar_pedido(self.admin, self.pedido))
        self.pedido.envio_id = 999  # simula ya despachado a courier
        self.assertTrue(permisos.puede_duplicar_pedido(self.logi, self.pedido))
        self.assertTrue(permisos.puede_duplicar_pedido(self.admin, self.pedido))
        self.assertFalse(permisos.puede_duplicar_pedido(self.dueno, self.pedido))   # ejecutivo nunca

    # --- notificar / es_logistica ---
    def test_puede_notificar(self):
        self.pedido.estado_comercial = EC.APROBADO
        self.assertTrue(permisos.puede_notificar(self.logi, self.pedido))
        self.assertTrue(permisos.puede_notificar(self.admin, self.pedido))
        self.assertFalse(permisos.puede_notificar(self.dueno, self.pedido))
        self.pedido.estado_comercial = EC.PENDIENTE
        self.assertFalse(permisos.puede_notificar(self.logi, self.pedido))

    def test_es_logistica(self):
        self.assertTrue(permisos.es_logistica(self.logi))
        self.assertTrue(permisos.es_logistica(self.admin))
        self.assertFalse(permisos.es_logistica(self.dueno))

    # --- querysets ---
    def test_queryset_visible(self):
        todos = Pedido.objects.all()
        self.assertEqual(permisos.queryset_visible(self.admin, todos).count(), 1)
        self.assertEqual(permisos.queryset_visible(self.dueno, todos).count(), 1)   # todos los suyos
        self.assertEqual(permisos.queryset_visible(self.ajeno, todos).count(), 0)
        self.assertEqual(permisos.queryset_visible(self.logi, todos).count(), 1)    # logística ve todo
        self.assertEqual(permisos.queryset_visible(self.sin_rol, todos).count(), 0)

    def test_queryset_para_ver(self):
        self.assertEqual(permisos.queryset_para_ver(self.admin).count(), 1)
        self.assertEqual(permisos.queryset_para_ver(self.dueno).count(), 1)
        self.assertEqual(permisos.queryset_para_ver(self.ajeno).count(), 0)
        self.assertEqual(permisos.queryset_para_ver(self.sin_rol).count(), 0)

    # --- campos editables ---
    def test_campos_editables(self):
        self.assertIsNone(permisos.campos_editables(self.admin, self.pedido))       # sin restricción
        ejec = permisos.campos_editables(self.dueno, self.pedido)
        logi = permisos.campos_editables(self.logi, self.pedido)
        self.assertIn("tipo_entrega", ejec)
        self.assertNotIn("retirar_en", ejec)        # ejecutivo NO edita dónde retirar
        self.assertIn("retirar_en", logi)           # logística SÍ
        self.assertNotIn("estado_comercial", ejec)  # estado nunca por edición directa
        self.assertEqual(permisos.campos_editables(self.sin_rol, self.pedido), [])


class PermisosMultiCodigoTest(TestCase):
    """Un perfil que gestiona DOS canales SAP ve los pedidos de ambos códigos (M2M `ejecutivos`)."""
    def setUp(self):
        self.ejec_a = crear_ejecutivo(codigo_sap=10, email="a@bioquimica.cl")
        self.ejec_b = crear_ejecutivo(codigo_sap=20, nombre="Canal B", email="b@bioquimica.cl")
        self.pa = crear_pedido(num="100", ejecutivo=self.ejec_a, estado_comercial=EC.PENDIENTE)
        self.pb = crear_pedido(num="200", ejecutivo=self.ejec_b, estado_comercial=EC.PENDIENTE)

        # ejecutivo con dos canales: código 10 (vía factory) + 20 (agregado a la M2M)
        self.multi = crear_usuario("multi@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)
        self.multi.perfil.ejecutivos.add(self.ejec_b)

    def test_codigos_sap_lista_ambos(self):
        self.assertEqual(sorted(self.multi.perfil.codigos_sap), [10, 20])

    def test_responsable_de_ambos_canales(self):
        self.assertTrue(permisos.responsable_del_pedido(self.multi, self.pa))
        self.assertTrue(permisos.responsable_del_pedido(self.multi, self.pb))

    def test_queryset_ve_pedidos_de_ambos(self):
        self.assertEqual(permisos.queryset_para_ver(self.multi).count(), 2)
        self.assertEqual(permisos.queryset_pedidos_ejecutivo(self.multi).count(), 2)
