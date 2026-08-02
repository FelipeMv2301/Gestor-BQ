from django.db import migrations


#Copia el código escalar legacy (codigo_empleado_sap) a la M2M `ejecutivos`, matcheando por codigo_sap.
#Idempotente: solo agrega si existe el Ejecutivo y aún no está vinculado. El escalar NO se toca (fallback).
def seed_ejecutivos(apps, schema_editor):
    PerfilUsuario = apps.get_model("cuentas", "PerfilUsuario")
    Ejecutivo = apps.get_model("ejecutivos", "Ejecutivo")

    for perfil in PerfilUsuario.objects.exclude(codigo_empleado_sap__isnull=True):
        ejecutivo = Ejecutivo.objects.filter(codigo_sap=perfil.codigo_empleado_sap).first()
        if ejecutivo:
            perfil.ejecutivos.add(ejecutivo)


def limpiar_ejecutivos(apps, schema_editor):
    PerfilUsuario = apps.get_model("cuentas", "PerfilUsuario")
    for perfil in PerfilUsuario.objects.all():
        perfil.ejecutivos.clear()


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0003_perfilusuario_ejecutivos"),
    ]

    operations = [
        migrations.RunPython(seed_ejecutivos, limpiar_ejecutivos),
    ]
