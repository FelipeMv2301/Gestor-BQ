# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado del repo

**En producción** (branch `produccion`; `desarrollo` despliega al ambiente `gestor-test`). Ya NO es un
skeleton: el proyecto está construido, corriendo y sincronizando pedidos reales de SAP y WooCommerce.

- **7 apps de dominio**: `cuentas`, `ejecutivos`, `pedidos`, `pedidosRechazados`, `envios`,
  `cotizaciones`, más `integraciones/` (paquete de clientes de sistemas externos, sin modelos).
- **Base de datos**: Postgres en prod, SQLite en dev — se elige por la variable `DATABASE_VERSION`
  (`SQLITE` → SQLite con WAL; cualquier otro valor → Postgres). Ver `gestorBQ/settings.py`.
- **Auth**: Google OAuth (`django-allauth`) restringido a `@bioquimica.cl`, validado server-side en
  `cuentas/adapters.py::BioquimicaSocialAccountAdapter`.
- **Cron**: sincronización SAP/Woo cada `INTERVALO_SYNC_PEDIDOS` minutos vía APScheduler
  (`pedidos/scheduler.py`), con lock en DB (`LockTarea`) para no duplicarse entre workers gunicorn.
- **Tests**: 172 tests (`pedidos/tests/` como paquete + `cuentas/tests.py`, `envios/tests.py`).
- **Deploy**: `Dockerfile` + `docker-compose.yml` + GitHub Actions (`.github/workflows/`) a un runner
  self-hosted; Caddy termina el TLS delante de gunicorn; Whitenoise sirve estáticos.
- **requirements.txt** existe y está pineado (Django 5.2.16, allauth, APScheduler, psutil, psycopg2,
  gunicorn, whitenoise, requests, python-dotenv).

La documentación de planificación en `backlog_proyecto/` sigue siendo la fuente de verdad de *qué falta*
y *en qué orden*, pero el código ya es la fuente de verdad de *qué está construido*. Ante conflicto entre
lo que dice un doc de `backlog_proyecto/` y lo que hace el código: **el código manda para el estado
actual**; los docs mandan para el diseño/backlog pendiente.

## Comandos

Activar venv (PowerShell, desde la raíz del repo):
```powershell
.venv\Scripts\Activate.ps1
```

Django (con venv activo):
```powershell
python manage.py runserver
python manage.py makemigrations
python manage.py migrate
python manage.py test              # suite completa
python manage.py test pedidos      # solo un app
python manage.py createsuperuser
```

Al instalar dependencias nuevas, regenerar el pin: `pip freeze > requirements.txt`.

Frontend (Tailwind, CLI standalone — **no** hay Node/npm, ver `Dockerfile`):
```powershell
tailwindcss -i static/css/tailwind-src.css -o static/css/app.css --minify
```
`app.css` es un build purgado: una clase Tailwind que no aparezca en algún `.html` escaneado **no existe
en el CSS compilado**. Reusar clases ya presentes o recompilar tras agregar clases nuevas.

Docker / deploy (en el servidor):
```powershell
docker compose build
docker compose up -d
docker compose exec -T app python manage.py migrate --noinput
docker compose exec -T app python manage.py collectstatic --noinput
```
El CI (`.github/workflows/`) hace esto automáticamente en cada push a `desarrollo` (→ `gestor-test`) y
a `produccion` (→ prod). El `.env` real nunca se versiona; el runner lo preserva con `rsync --exclude`.

Management commands propios (app `cotizaciones`): `sondear_cotizacion`, `sondear_cadena`,
`recalcular_facturacion`.

## Documentos clave

- `backlog_proyecto/plan-portal-logistica-comercial.md` — diseño/arquitectura narrativo original.
  Útil como historia del *por qué*, pero varias decisiones ya están implementadas (ver más abajo).
- `backlog_proyecto/backlog_historias_portal_logistica_comercial.md` — backlog de HU en Markdown
  (grep-eable). Fuente de verdad del *qué* y el orden pendiente.
- `backlog_proyecto/backlog-frontend-portal.md` — estado real y deuda técnica del frontend
  (sección "Corte de estado real").
- `backlog_proyecto/backlog-historias-portal-logistica-comercial (1).xlsx` — mismo backlog en Excel.

El sistema reimplementó, **dentro de este repo**, la lógica que antes vivía en el proyecto FastAPI
`gestor_despachos_retiros` (`ChibraService`, `SapServiceGestor`, `WooServiceGestor`, `MAP_EMPLEADOS`,
`ServicioCorreoGestor`). Sus equivalentes aquí:
- `integraciones/sap_client.py`, `integraciones/woo_client.py`, `integraciones/chibra_client.py`,
  `integraciones/moveup_client.py`, `integraciones/email_client.py`, `integraciones/seguimiento.py`.
- `MAP_EMPLEADOS`/`EMAIL_EJECUTIVOS` hardcodeados → modelo `ejecutivos.Ejecutivo` (datos en DB).

## Arquitectura (implementada)

**Objetivo cumplido**: reemplazó la planilla Google Sheets que sincronizaba NV de SAP por una app
Django donde Comercial revisa/edita cada pedido y Logística gestiona courier, notifica al cliente y
documenta el envío en el courier (Chibra/MoveUP).

**Capas** (respetar al tocar código — ver "Convenciones de colaboración"):
- `models.py` — datos + `PedidoQuerySet` (filtros componibles: `buscar`, `con_estado_*`, etc.).
- `pedidos/services.py` — reglas de negocio de ingesta y acciones (guardar SAP/Woo, rechazar,
  reingresar, notificar).
- `pedidos/permisos.py` — **toda** la autorización, un solo punto de verdad.
- `envios/services.py` — validación y despacho a courier (dict-dispatch por courier).
- `integraciones/*` — un cliente por sistema externo. Las vistas nunca pegan directo a una API.
- `pedidos/views/` — solo orquestan + presentan.

**Ingesta (cron)**: `guardar_pedidos_sap` / `guardar_pedidos_woo` traen NV recientes, deduplican contra
`Pedido` existente y contra `PedidoRechazado`, y crean el `Pedido`. El filtro SAP es
`U_BQ_CrearEnvio eq 'Y'` combinado con `TransportationCode`/`U_BQ_TipoEntrega`.

**Estados de un pedido** — OJO, esto cambió respecto del plan original:
- `estado_comercial`: `PENDIENTE` / `APROBADO`. **La ingesta (SAP y Woo) entra directo como
  `APROBADO`** — no hay flujo `PENDIENTE→APROBADO` por botón. `PENDIENTE` prácticamente no se usa hoy.
- `estado_notificacion`: `NO_NOTIFICADO` / `NOTIFICADO` (lo dispara Logística al notificar al cliente).
- **Rechazo**: `pedidos/services.py::rechazar_pedido` mueve el registro a `pedidosRechazados.PedidoRechazado`
  (snapshot) y borra el `Pedido`. No hay estado `RECHAZADO` en el propio `Pedido`.
- `Pedido.estado_seguimiento` (property) combina `tipo_entrega` + `estado_notificacion` + `envio_id`
  en un único badge — es la fuente de verdad para la UI, no combinar filtros a mano.

**Roles** (`cuentas.PerfilUsuario.rol`: `EJECUTIVO` / `LOGISTICA` / `ADMIN`) se asignan a mano en
`/admin/`. El rol `ADMIN` del portal **no** equivale a `is_staff` de Django (las cuentas de Google
login nunca entran a `/admin/`).

**Multi-código SAP por perfil**: `PerfilUsuario.ejecutivos` es un M2M a `Ejecutivo`; la visibilidad se
lee **siempre** vía la property `PerfilUsuario.codigos_sap` (prefiere la M2M, cae al escalar legacy
`codigo_empleado_sap` si la M2M está vacía). Nunca filtrar por el escalar directo.

**Couriers**: `envios/services.py` despacha por dict-dispatch (`SELECCIONAR_COURIER`,
`PARSEAR_DESPACHO`). Hoy: Chibra y MoveUP. Agregar un courier = agregar entrada al dict + su parser +
su cliente en `integraciones/`, sin tocar el flujo.

**Cotizaciones** (`cotizaciones/`): módulo aparte que consulta Quotations de SAP (sondeo vía
`sondear_cotizacion`/`sondear_cadena`) y calcula facturación. `PerfilUsuario.ve_todas_cotizaciones`
marca al supervisor comercial que ve las de todos los ejecutivos.

## Infraestructura — decisiones resueltas (conservar el porqué)

**Sesión SAP compartida (HU-0.5) — RESUELTO, implementado en `integraciones/sap_client.py`**: no se
construye instancia propia ni Redis in-house. Se usa **Token-SAP-BQ**, servicio externo (desplegado en
Railway, `numReplicas: 1` — singleton en memoria, no tocar esa config) que centraliza login/sesión SAP
compartida (`b1session`+`routeid`) vía `POST /session` y `POST /session/invalidate`. `service_name` del
proyecto: `gestor-bq` (credenciales en `.env`, nunca versionadas). Desde `gestorBQ` se pega directo al
Service Layer de SAP con las cookies recibidas; en 401 se invalida y se re-pide sesión — no se llama
`/Login` desde este repo.

**Red de Postgres (HU-0.4) — RESUELTO, en producción**: el server Postgres (`192.168.0.165`) es hardware
propio en la LAN de la oficina (ahorro de nube, sin requisito de compliance). **Django corre en el mismo
servidor/LAN que Postgres** (Docker + gunicorn + Caddy), no en Railway. Postgres nunca escucha fuera de
`localhost`/LAN — no se abre 5432 a Internet ni se monta VPN para llegar a la DB. El contenedor llega al
Postgres nativo del host vía `host.docker.internal` (alias `host-gateway` en `docker-compose.yml`).

Se descartó Django-en-Railway + Postgres on-prem por fricción real: Railway sin Pro no da IP de salida
fija, y el Pro la da **compartida**; Tailscale en contenedor Railway solo corre en modo *userspace* (solo
proxy SOCKS5, que `psycopg2`/libpq no soporta). Acceso remoto (teletrabajo) de Comercial/Logística:
**no** por VPN por persona — el server expone solo el **443** (HTTPS) hacia Django y la barrera real es
el login Google OAuth `@bioquimica.cl`. Excepción: Tailscale (plan free) sí para acceso de
**administrador** directo a Postgres (`psql`/pgAdmin), pocas personas.

## Puntos abiertos / spikes (revisar antes de tocar lo relacionado)

- **HU-3.3 write-back a SAP**: hoy el estado se maneja **solo internamente** — no se escribe
  `U_BQ_CrearEnvio` de vuelta a SAP. Confirmar con Felipe si eso debe cambiar.
- **HU-3.4 `U_BQ_TipoEntrega`**: el filtro de ingesta ya trata `HOME` y `BRANCH` como coexistentes
  (`TransportationCode eq 1 and (U_BQ_TipoEntrega eq 'HOME' or 'BRANCH')`), y `TransportationCode eq 3`
  como retiro. Resuelto en código.
- **HU-4.4 rechazo**: hoy `puede_rechazar` = Admin siempre, Ejecutivo dueño solo hasta que hay envío
  (`envio_id is None`). Logística no rechaza explícitamente. Confirmar si Logística debe poder.
- Deuda anotada en el propio código: `envios/services.py::validar_pedidos_para_despacho` agrupa por RUT
  único ("puede causar errores innecesarios", ver comentario ahí).

## Convenciones de trabajo

- Si un doc de `backlog_proyecto/` y el código difieren sobre el **estado actual**, manda el código.
  Sobre **prioridad/alcance pendiente**, manda el backlog; sobre **diseño técnico pendiente**, el `.md`.
- Los spikes deben confirmarse con Felipe antes de codear la historia que dependa de ellos.
- No asumas nada que no sepas con certeza. Investígalo (codegraph, código, tests) y llega a una
  respuesta coherente antes de afirmar.

## Convenciones de colaboración con Claude

- **Solo asesoría / control de Felipe:** no codear sin indicación explícita de "hazlo tú". Ante una
  tarea, proponer + explicar; codear solo cuando Felipe lo pide.
- **Reparto:** el **frontend (templates)** lo puede hacer Claude; cualquier función
  **Python/Django/backend** (views, urls, permisos, servicios, modelos) Felipe prefiere escribirla él —
  Claude indica **qué y dónde**.
- **Reusar, nunca reescribir lógica:** las reglas de negocio viven en `pedidos/services.py`,
  `pedidos/permisos.py`, `pedidos/models.py::PedidoQuerySet`, `integraciones/*`, `envios/services.py`.
  Las vistas solo orquestan + presentan. Antes de escribir algo nuevo, buscar si ya existe y reusarlo.
- **Front:** Tailwind (CLI standalone, `app.css` compilado y purgado — **no CDN**) + HTMX. Diseño
  **"Design B" teal** con tokens CSS-var en `base.html` (claro/oscuro). Usar **rem**, nunca px fijo,
  para que el control A−/A+ escale. Libs de terceros **vendorizadas** en `static/vendor/` (no CDN),
  con la versión en el nombre del archivo.
- **Nombres de variables legibles**, no placeholders compactos.
- **codegraph** está indexado (`.codegraph/`) — usarlo para mapear la lógica existente antes de tocar código.
- **Tests** en `pedidos/tests/` (paquete): permisos, modelos, scheduler, servicios, vistas, integraciones
  mockeadas. Correr `python manage.py test` antes de refactorizar.
