# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Estado del repo

Skeleton Django recién creado (`django-admin startproject gestorBQ .`), sin apps propias todavía.
`gestorBQ/settings.py` está en su forma vanilla generada por Django: SQLite, `INSTALLED_APPS` solo
con los apps de `django.contrib.*`, sin `django-allauth` ni ningún modelo de dominio. No existe
`requirements.txt` — el único paquete instalado en `.venv` es `Django==5.2.16` (+ deps transitivas:
`asgiref`, `sqlparse`). No hay tests, lint config ni CI.

La documentación de planificación en `backlog_proyecto/` es la fuente de verdad de *qué construir* y
*en qué orden* — léela antes de asumir estructura de apps, modelos o nombres de campos.

## Comandos

Activar venv (PowerShell, desde la raíz del repo):
```powershell
.venv\Scripts\Activate.ps1
```

Comandos Django estándar (con venv activo):
```powershell
python manage.py runserver
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

No hay `requirements.txt` aún — al instalar dependencias nuevas (`django-allauth`, driver de
Postgres, etc.) generarlo con `pip freeze > requirements.txt`.

## Documentos clave

- `backlog_proyecto/plan-portal-logistica-comercial.md` — diseño/arquitectura narrativo del
  proyecto a construir (Portal Logística + Comercial). Estado: propuesta en diseño, ajustada con
  Felipe (2026-07-09), **no implementado**. Incluye los modelos de dominio propuestos (`PerfilUsuario`,
  `Ejecutivo`, `Pedido`, `PedidoRechazado`) con sus campos.
- `backlog_proyecto/backlog_historias_portal_logistica_comercial.md` — volcado en Markdown del
  backlog (mismo contenido que el xlsx), útil para leer/grep sin abrir Excel.
- `backlog_proyecto/backlog-historias-portal-logistica-comercial (1).xlsx` — fuente de verdad para
  historias de usuario (HU), spikes, prioridad y estado de avance. El `.md` de diseño describe el
  *por qué* y el *cómo*; el xlsx/backlog describe el *qué* y en qué orden.

El plan reemplaza el alcance de negocio de un documento anterior (`docs/plan-portal-despachos-django.md`,
de otro repo), pero mantiene su parte técnica: stack Django y reutilización de servicios ya
existentes en el sistema actual de despachos (`ChibraService`, `SapServiceGestor`, `WooServiceGestor`,
`MAP_EMPLEADOS`, `ServicioCorreoGestor`). Esos módulos **no viven en este repo** — pertenecen al
sistema FastAPI actual de `gestor_despachos_retiros` que este proyecto va a reemplazar/extender.

## Resumen de la arquitectura planeada

**Objetivo del proyecto**: reemplazar la planilla Google Sheets que hoy sincroniza NV de SAP
(cron `fetch_orders_by_date`) por una app Django donde:
- **Comercial** revisa/edita cada NV entrante (contacto, dirección, courier, observaciones) antes de
  pasarla a Logística.
- **Logística** ve la tabla maestra de pedidos ya confirmados, gestiona courier, dispara
  notificación al cliente y documenta el envío en Chibra.

**Stack decidido**: Django + Postgres (hoy el settings sigue en SQLite — migrar antes de HU-0.4).
Auth vía Google OAuth institucional (`django-allauth`), con validación server-side de dominio
`@bioquimica.cl` (el hint `hd=` de Google no basta, se valida en `pre_social_login`/`save_user` de
un adapter custom).

**Apps de dominio previstas** (sección 5 del plan), ninguna creada aún:
- `cuentas` — `PerfilUsuario` (rol, `sap_employee_code`, activo).
- `ejecutivos` — `Ejecutivo` (reemplaza `MAP_EMPLEADOS`/`EMAIL_EJECUTIVOS` hardcodeados).
- `pedidos` — `Pedido` y `PedidoRechazado`.
- `notificaciones` — `NotificacionEnvio`.
- `chibra` — `EnvioChibra`.

**Roles** (`PerfilUsuario.rol`: `LOGISTICA` / `EJECUTIVO` / `ADMIN`) se asignan a mano por un Admin
en `/admin/` — no se infieren de Google Groups/Workspace. Primer login crea `PerfilUsuario` con
`rol=None` → pantalla de espera de activación.

**Máquina de estados de un pedido** (`Pedido.estado_comercial`):
`PENDIENTE` (ingesta automática o carga manual) → `APROBADO` (acción manual del ejecutivo, botón
"Aprobar"; Logística ya no permite edición a Comercial) → `RECHAZADO` (acción explícita, sin
equivalente en SAP, mueve el registro a `PedidoRechazado` archivado). `estado_notificacion` es un
campo aparte que Logística dispara al notificar al cliente.

**Gestor de sesión SAP compartido (HU-0.5) — RESUELTO (2026-07-10)**: no se construye instancia
propia ni Redis in-house. Se usa **Token-SAP-BQ**, servicio externo ya desplegado en Railway
(`token-sap-bq-production.up.railway.app`, `numReplicas: 1` — no tocar esa config, es singleton en
memoria) que centraliza login/sesión SAP compartida (`b1session`+`routeid`+`sap_db`) vía
`POST /session` y `POST /session/invalidate`. `service_name` de este proyecto: `gestor-bq` (password
va en variable de entorno / `.env`, nunca versionada). Desde `gestorBQ` se pega directo al Service
Layer de SAP con las cookies recibidas — no se vuelve a llamar `/Login` desde este repo.

**Puntos todavía abiertos** (ver sección "Spikes" del plan antes de implementar):
- Si el botón "Aprobar" además escribe `U_BQ_CrearEnvio='Y'` de vuelta a SAP (write-back) o el
  estado se maneja solo internamente (HU-3.3).
- Si el valor `HOME` de `U_BQ_TipoEntrega` reemplaza o coexiste con `BRANCH`/`1`/`3` (HU-3.4).
- Si "Rechazar" es exclusivo de Comercial en `PENDIENTE` o también disponible para Logística sobre
  `APROBADO` (HU-4.4).

## Convenciones de trabajo

- El plan y el backlog (xlsx/md) pueden divergir en el tiempo — si hay conflicto sobre prioridad o
  alcance de una historia, el backlog manda; si es sobre diseño técnico, el `.md` de diseño manda.
- Los "Spikes" listados al final del plan deben resolverse (confirmar con Felipe) antes de
  codear la historia que dependa de ellos.
- HU-0.4 (Postgres) y HU-1.4 (modelos/migraciones) son la base de la Fase 0-1 — no crear apps de
  dominio ni escribir modelos sin antes resolver el cambio de settings a Postgres.
