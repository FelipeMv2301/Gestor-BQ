from types import SimpleNamespace
from unittest.mock import Mock
from django.contrib.auth.models import User
from django.test import TestCase, Client
from allauth.core.exceptions import ImmediateHttpResponse
from .adapters import BioquimicaSocialAccountAdapter
from .models import PerfilUsuario
from ejecutivos.models import Ejecutivo
from pedidos.tests.factories import crear_usuario

Rol = PerfilUsuario.Rol


#`is_existing` y `connect` los usa la reconciliación por email de pre_social_login: sin ellos, el
#doble se queda corto y el test revienta con AttributeError en vez de probar algo.
def _sociallogin(email, is_existing=False):
    return SimpleNamespace(
        account=SimpleNamespace(extra_data={"email": email}),
        is_existing=is_existing,
        connect=Mock(),
    )


class BioquimicaSocialAccountAdapterTest(TestCase):
    def setUp(self):
        self.adapter = BioquimicaSocialAccountAdapter()

    def test_dominio_permitido_pasa(self):
        self.adapter.pre_social_login(None, _sociallogin("persona@bioquimica.cl"))  # no debe lanzar

    def test_login_ya_enlazado_no_intenta_reconciliar(self):
        sociallogin = _sociallogin("persona@bioquimica.cl", is_existing=True)
        self.adapter.pre_social_login(None, sociallogin)
        sociallogin.connect.assert_not_called()

    def test_reconcilia_con_el_usuario_existente_del_mismo_email(self):
        """Sin esto, allauth trataría el login como registro nuevo y caería al formulario de signup."""
        usuario = User.objects.create(username="ya.estaba", email="ya.estaba@bioquimica.cl")
        sociallogin = _sociallogin("YA.ESTABA@bioquimica.cl")  # el match es case-insensitive
        self.adapter.pre_social_login(None, sociallogin)
        sociallogin.connect.assert_called_once()
        self.assertEqual(sociallogin.connect.call_args[0][1], usuario)

    def test_sin_usuario_previo_no_reconcilia_nada(self):
        sociallogin = _sociallogin("nuevo@bioquimica.cl")
        self.adapter.pre_social_login(None, sociallogin)
        sociallogin.connect.assert_not_called()

    def test_dominio_no_permitido_rechaza(self):
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(None, _sociallogin("persona@gmail.com"))

    def test_dominio_similar_pero_distinto_rechaza(self):
        # ataque típico: dominio que "contiene" el permitido pero no termina en él
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(None, _sociallogin("persona@bioquimica.cl.evil.com"))

    def test_email_vacio_rechaza(self):
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(None, _sociallogin(""))


class AdminDeDjangoCerradoParaCuentasDelPortalTest(TestCase):
    """HU-F7.4: el rol 'ADMIN' de PerfilUsuario es un campo propio de esta app, no equivale a
    User.is_staff de Django — las cuentas de Google login nunca deben poder entrar a /admin/."""

    def test_cuenta_con_rol_admin_de_la_app_no_tiene_is_staff(self):
        usuario = crear_usuario("admin_app@bioquimica.cl", Rol.ADMIN)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)

    def test_cuenta_con_rol_admin_de_la_app_no_puede_entrar_al_admin_de_django(self):
        usuario = crear_usuario("admin_app2@bioquimica.cl", Rol.ADMIN)
        client = Client()
        client.force_login(usuario)
        resp = client.get("/admin/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp.url)


class InicioLandingPorRolTest(TestCase):
    """HU-F0.5: cada rol cae directo en su pantalla, sin pasar por una home genérica."""

    def setUp(self):
        self.client = Client()

    def test_ejecutivo_va_a_mis_pedidos(self):
        self.client.force_login(crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10))
        resp = self.client.get("/cuentas/inicio/")
        self.assertRedirects(resp, "/pedidos/mis-pedidos/")

    def test_logistica_va_a_despachos(self):
        self.client.force_login(crear_usuario("logi@bioquimica.cl", Rol.LOGISTICA))
        resp = self.client.get("/cuentas/inicio/")
        self.assertRedirects(resp, "/pedidos/despachos/")

    def test_admin_va_a_panel_admin(self):
        self.client.force_login(crear_usuario("admin@bioquimica.cl", Rol.ADMIN))
        resp = self.client.get("/cuentas/inicio/")
        self.assertRedirects(resp, "/pedidos/panel/")

    def test_sin_rol_ve_pantalla_de_espera(self):
        self.client.force_login(crear_usuario("nuevo@bioquimica.cl", None))
        resp = self.client.get("/cuentas/inicio/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "cuentas/esperando_activacion.html")


class PanelPerfilesTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.ejec = crear_usuario("ejec@bioquimica.cl", Rol.EJECUTIVO, codigo_sap=10)

    def test_no_admin_no_puede_ver_el_panel(self):
        self.client.force_login(self.ejec)
        resp = self.client.get("/cuentas/panel/perfiles/")
        # no se sigue el redirect: "inicio" a su vez redirige a mis_pedidos (encadenado)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/cuentas/inicio/")

    def test_admin_ve_el_panel(self):
        self.client.force_login(self.admin)
        resp = self.client.get("/cuentas/panel/perfiles/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ejec@bioquimica.cl")


class AutoAsignaCodigoSapEnPrimerLoginTest(TestCase):
    """cuentas/signals.py::crear_perfil_usuario — lo que Felipe pidió: en el primer login, si el email
    matchea un Ejecutivo activo de SAP, el código se autoasigna solo. Segundo login no lo toca; el Admin
    puede cambiarlo después sin que nada lo revierta."""

    def test_primer_login_con_match_autoasigna_codigo(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True)
        usuario = User.objects.create(username="elsa@bioquimica.cl", email="elsa@bioquimica.cl")
        self.assertEqual(usuario.perfil.codigo_empleado_sap, 10)

    def test_primer_login_sin_match_no_asigna_nada(self):
        usuario = User.objects.create(username="nadie@bioquimica.cl", email="nadie@bioquimica.cl")
        self.assertIsNone(usuario.perfil.codigo_empleado_sap)

    def test_ejecutivo_inactivo_no_matchea(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=False)
        usuario = User.objects.create(username="elsa@bioquimica.cl", email="elsa@bioquimica.cl")
        self.assertIsNone(usuario.perfil.codigo_empleado_sap)

    def test_codigo_ya_tomado_por_otro_perfil_no_se_duplica(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True)
        crear_usuario("primero@bioquimica.cl", codigo_sap=10)  # ya tiene el código 10
        segundo = User.objects.create(username="elsa@bioquimica.cl", email="elsa@bioquimica.cl")
        self.assertIsNone(segundo.perfil.codigo_empleado_sap)  # no se puede repetir (unique=True)

    def test_segundo_login_no_reejecuta_ni_pisa_cambios(self):
        Ejecutivo.objects.create(codigo_sap=10, nombre="Elsa Martínez", email="elsa@bioquimica.cl", activo=True)
        usuario = User.objects.create(username="elsa@bioquimica.cl", email="elsa@bioquimica.cl")
        usuario.perfil.codigo_empleado_sap = 99  # el Admin lo cambió a mano
        usuario.perfil.save()

        usuario.save()  # "segundo login" -> post_save de User otra vez, pero created=False

        usuario.perfil.refresh_from_db()
        self.assertEqual(usuario.perfil.codigo_empleado_sap, 99)  # sigue el que puso el Admin, no se revierte


class EditarPerfilTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = crear_usuario("admin@bioquimica.cl", Rol.ADMIN)
        self.usuario = crear_usuario("nuevo@bioquimica.cl", None)

    def test_no_admin_no_puede_editar(self):
        self.client.force_login(self.usuario)
        resp = self.client.post(f"/cuentas/panel/perfiles/{self.usuario.perfil.pk}/editar/",
                                 {"rol": Rol.ADMIN})
        self.usuario.perfil.refresh_from_db()
        self.assertIsNone(self.usuario.perfil.rol)  # no cambió nada

    def test_admin_asigna_rol_y_codigo(self):
        Ejecutivo.objects.create(codigo_sap=30, nombre="Canal 30", email="c30@bioquimica.cl", activo=True)
        self.client.force_login(self.admin)
        resp = self.client.post(f"/cuentas/panel/perfiles/{self.usuario.perfil.pk}/editar/",
                                 {"rol": Rol.EJECUTIVO, "codigos_sap": "30"})
        self.assertEqual(resp.status_code, 200)
        self.usuario.perfil.refresh_from_db()
        self.assertEqual(self.usuario.perfil.rol, Rol.EJECUTIVO)
        self.assertEqual(self.usuario.perfil.codigos_sap, [30])

    def test_admin_asigna_dos_codigos_a_mano(self):
        Ejecutivo.objects.create(codigo_sap=30, nombre="Canal 30", email="c30@bioquimica.cl", activo=True)
        Ejecutivo.objects.create(codigo_sap=40, nombre="Canal 40", email="c40@bioquimica.cl", activo=True)
        self.client.force_login(self.admin)
        resp = self.client.post(f"/cuentas/panel/perfiles/{self.usuario.perfil.pk}/editar/",
                                 {"rol": Rol.EJECUTIVO, "codigos_sap": "30, 40"})
        self.assertEqual(resp.status_code, 200)
        self.usuario.perfil.refresh_from_db()
        self.assertEqual(sorted(self.usuario.perfil.codigos_sap), [30, 40])

    def test_admin_codigo_inexistente_da_error(self):
        self.client.force_login(self.admin)
        resp = self.client.post(f"/cuentas/panel/perfiles/{self.usuario.perfil.pk}/editar/",
                                 {"rol": Rol.EJECUTIVO, "codigos_sap": "999"})
        self.usuario.perfil.refresh_from_db()
        self.assertEqual(self.usuario.perfil.codigos_sap, [])   # no se guardó nada
