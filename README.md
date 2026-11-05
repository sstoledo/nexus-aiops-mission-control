# AIOps Mission Control — NEXUS E-COMMERCE

Stack local de monitoreo, alertas y análisis de incidentes para la plataforma
simulada **NEXUS E-COMMERCE**. Equipo **Sentinel Ops** — Gerencia de Tecnologías
de Información, Ciclo IX (Huacho, Perú, 2026).

Todo corre en contenedores Docker sobre Windows, sin máquina virtual Linux
tradicional: el mismo `docker-compose.yml` produce un entorno idéntico en la
máquina de cada integrante.

---

## 1. Arquitectura del stack

| Componente | Tipo | Puerto host | Rol |
|---|---|---|---|
| `node-exporter` | **Real** | 9100 | Métricas de CPU, memoria, disco y red del sistema base |
| `prometheus` | Real | 9090 | Recolección, almacenamiento y evaluación de reglas |
| `alertmanager` | Real | 9093 | Agrupación, inhibición y enrutamiento por severidad |
| `grafana` | Real | 3000 | Dashboards provisionados automáticamente |
| `app` | **Simulado** | 8080 | Aplicación de comercio + exporter propio de métricas |
| `db` | **Simulado** | interno | PostgreSQL con catálogo y pedidos |

**Métricas propias de la aplicación** (lo que un exporter de sistema no puede ver):

| Métrica Prometheus | Tipo | Requisito del proyecto |
|---|---|---|
| `nexus_app_response_time_seconds` | Histogram | Tiempo de respuesta |
| `nexus_app_http_500_total` | Counter | Errores HTTP 500 |
| `nexus_db_active_connections` | Gauge | Conexiones activas a la BD |
| `nexus_db_up` | Gauge | Disponibilidad de la BD |
| `nexus_alerts_received_total` | Counter | Alertas entregadas por Alertmanager |

---

## 2. Requisitos

- Windows 10/11 con **Docker Desktop** (backend WSL2) y `docker compose` v2.
- Puertos libres: `3000`, `8080`, `9090`, `9093`, `9100`.
- ~2 GB de RAM libres para los contenedores.

Verificación rápida:

```powershell
docker --version
docker compose version
```

---

## 3. Puesta en marcha

Desde la raíz del proyecto, en PowerShell:

```powershell
# 1. Levantar todo el stack (la primera vez construye la imagen de la app)
docker compose up -d --build

# 2. Ver estado y salud de los servicios
docker compose ps
```

Espera a que `nexus-db` y `nexus-app` aparezcan como `healthy` (30–60 s la
primera vez). Después abre:

| Interfaz | URL | Credenciales |
|---|---|---|
| Grafana | http://localhost:3000 | `admin` / `sentinel2026` |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | — |
| App NEXUS (health) | http://localhost:8080/health | — |
| Node Exporter | http://localhost:9100/metrics | — |

El dashboard **AIOps Mission Control — NEXUS E-COMMERCE** ya está provisionado y
es la página de inicio de Grafana: no hay que crear datasources ni paneles a mano.

Comandos de operación:

```powershell
docker compose logs -f prometheus      # reglas y recolección
docker compose logs -f alertmanager    # enrutamiento de alertas
docker compose logs -f app             # alertas recibidas en /alerts
docker compose down                    # detener (conserva datos)
docker compose down -v                 # detener y borrar datos
```

---

## 4. Las tres reglas de alerta obligatorias (Fase 4)

Definidas en `prometheus/rules.yml`, grupo `nexus-aiops-required`:

| # | Alerta | Expresión | Duración | Severidad |
|---|---|---|---|---|
| 1 | `NexusHighCpuUsage` | `100 - (avg by (instance_name) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100) > 90` | 2 min | `high` |
| 2 | `NexusCriticalMemory` | `(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 10` | 2 min | `high` |
| 3 | `NexusTargetDown` | `up == 0` | 1 min | `critical` |

Verificación de que las reglas están cargadas:

```powershell
# Debe listar las 7 reglas con su estado (inactive / pending / firing)
curl http://localhost:9090/api/v1/rules

# O en la UI: http://localhost:9090/rules
```

### 4.1 Demostrar la regla de CPU (Alta)

```powershell
# Genera carga de CPU durante 5 minutos en la misma VM Linux de Docker
docker compose --profile chaos up -d chaos-cpu
```

Cronología esperada: a los ~15 s el panel de CPU sube por encima del 90 %, la
alerta pasa a `pending` en Prometheus y a los **2 minutos** entra en `firing`.
Se puede ver en http://localhost:9093 y en los logs de la app:

```powershell
docker compose logs -f app | Select-String "ALERT"
```

Para detener la carga: `docker compose --profile chaos stop chaos-cpu`

### 4.2 Demostrar la regla de memoria (Alta)

Es la regla más difícil de reproducir de forma segura en WSL2, porque llenar la
memoria del VM de Docker puede reiniciar Docker Desktop. Dos opciones válidas:

**Opción A — demostración controlada (recomendada en la exposición):**

```powershell
# Ocupa el 60% de la RAM del VM de Docker durante 4 minutos
docker run --rm -d --name nexus-mem-stress polinux/stress `
  stress --vm 1 --vm-bytes 60% --timeout 240s
```

Sube el porcentaje por pasos (60 %, 75 %) hasta que Grafana muestre la memoria
disponible bajo 10 %. Si Docker Desktop se vuelve inestable, reinícialo y el
stack se recupera solo por las políticas `restart: unless-stopped`.

**Opción B — demostración sin riesgo:** mostrar en Prometheus
(`http://localhost:9090/graph`) la expresión de la regla evaluando en tiempo
real y explicar el umbral. La regla está cargada y evaluándose; lo que no se
fuerza es la condición.

### 4.3 Demostrar la regla de objetivo no disponible (Crítica)

```powershell
# Detener la aplicación: Prometheus deja de poder scrapearla
docker compose stop app
```

Cronología esperada: el objetivo `nexus-app` pasa a `DOWN` en
http://localhost:9090/targets y a los **60 segundos** la alerta
`NexusTargetDown` está en `firing` con severidad `critical`.

```powershell
docker compose start app   # restaurar
```

---

## 5. Simulación de incidentes de aplicación (componentes simulados)

La app expone endpoints de caos para reproducir incidentes sin tocar la
configuración:

```powershell
# 20 respuestas HTTP 500 consecutivas -> alerta NexusHighErrorRate
curl -X POST "http://localhost:8080/chaos/fail?count=20"

# Latencia de 2 s por petición -> alerta NexusSlowResponse
curl -X POST "http://localhost:8080/chaos/latency?ms=2000"

# Generar tráfico real hacia los endpoints afectados
1..30 | ForEach-Object { curl.exe -s -o NUL http://localhost:8080/api/products }

# Limpiar el caos inyectado
curl -X POST "http://localhost:8080/chaos/reset"
```

Las reglas opcionales (`nexus-aiops-application`, en `rules.yml`) disparan con
`HTTP 500 > 5/min`, `p95 > 1.5 s` y saturación del pool de conexiones. Las tres
reglas obligatorias viven en un grupo separado y no dependen de ellas.

---

## 6. Severidades y enrutamiento (Alertmanager)

`alertmanager/alertmanager.yml` implementa el enrutamiento por severidad que
exige la Fase 4:

| Severidad | `group_wait` | `group_interval` | `repeat_interval` |
|---|---|---|---|
| `critical` | 5 s | 30 s | 30 min |
| `high` | 10 s | 1 min | 1 h |

El receptor es la propia aplicación (`http://app:8000/alerts`), así la demo es
autocontenida: cada alerta queda registrada en los logs del contenedor `app` y
contabilizada en la métrica `nexus_alerts_received_total` del dashboard, sin
necesitar SMTP ni cuenta de Slack.

También hay una **regla de inhibición**: mientras un objetivo esté caído
(`NexusTargetDown`), se silencian las alertas de capacidad del mismo objetivo,
porque el síntoma ya está explicado por la causa.

Para usar correo real, descomenta el bloque `Optional: real email delivery` al
final del archivo (requiere una *app password* de Gmail, no la contraseña normal).

---

## 7. Validar la configuración sin levantar el stack

```powershell
docker compose config --quiet

docker run --rm -v "${PWD}/prometheus:/etc/prometheus:ro" `
  --entrypoint promtool prom/prometheus:v3.1.0 `
  check config /etc/prometheus/prometheus.yml

docker run --rm -v "${PWD}/alertmanager:/cfg:ro" `
  --entrypoint amtool prom/alertmanager:v0.28.0 `
  check-config /cfg/alertmanager.yml
```

---

## 8. Nota importante sobre `node-exporter` en Docker Desktop (Windows)

En Docker Desktop el kernel Linux vive en la **VM de WSL2**, no en Windows.
`node-exporter` lee `/host` (el rootfs de esa VM), por lo que las métricas de
CPU, memoria y disco corresponden **a la VM de Docker**, no al Windows anfitrión.

Esto es correcto y suficiente para el proyecto: los contenedores del stack corren
en esa misma VM, de modo que la carga que generan sí se refleja en las métricas y
las tres reglas se disparan como se espera. Si el docente pide métricas del
Windows real, la vía es **Windows Exporter** (`windows_exporter`) en el host y un
target adicional en `prometheus.yml`.

---

## 9. Estructura del proyecto

```
.
├── docker-compose.yml
├── .env                          # credenciales locales de la simulación
├── README.md
├── alertmanager/
│   └── alertmanager.yml          # rutas por severidad + inhibición
├── app/
│   ├── app.py                    # aplicación simulada + exporter Prometheus
│   ├── wsgi.py                   # entrypoint de gunicorn
│   ├── requirements.txt
│   └── Dockerfile
├── db/
│   └── init.sql                  # esquema y datos de NEXUS E-COMMERCE
├── prometheus/
│   ├── prometheus.yml            # targets y conexión con Alertmanager
│   └── rules.yml                 # 3 reglas obligatorias + 4 opcionales
└── grafana/
    ├── provisioning/
    │   ├── datasources/prometheus.yml
    │   └── dashboards/dashboards.yml
    └── dashboards/nexus-aiops-overview.json
```

---

## 10. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `nexus-app` reinicia en bucle | La BD aún no acepta conexiones | Esperar 30 s; `docker compose logs app` |
| Target `nexus-app` en `DOWN` | El contenedor no está `healthy` | `docker compose ps`, revisar `app/` |
| Grafana sin datos | Datasource no provisionado | `docker compose restart grafana` |
| Alertas no llegan | `alertmanager` no resuelve `app` | Ambos deben estar en `nexus-net` |
| Puerto ocupado | Otro servicio en 3000/9090/9100 | `netstat -ano \| findstr :9090` |
| Docker sin espacio | Imágenes y volúmenes acumulados | `docker system prune` (revisar antes qué elimina) |
| Panel de conexiones plano en 1 | El pool solo abre conexiones bajo concurrencia real | Normal: el gauge mide el footprint del pool |

---

## 11. Registro de verificación (2026-11-05)

Pruebas ejecutadas sobre el stack real, no solo validación sintáctica:

| Prueba | Resultado |
|---|---|
| `docker compose config` / `promtool` / `amtool` | Válidos: 7 reglas, 1 receptor |
| 6 contenedores | Todos `healthy` |
| Targets de Prometheus | 3/3 `up` (prometheus, node, nexus-app) |
| App + PostgreSQL | `/api/products` y `/api/orders` responden con datos reales |
| Dashboard Grafana | Provisionado con 10 paneles, datasource `nexus-prometheus` |
| **`NexusTargetDown`** (crítica) | Disparó a los 60 s de detener `node-exporter`, entregada al webhook, resuelta a los 60 s |
| **`NexusHighCpuUsage`** (alta) | Disparó a los 2 min con CPU al 99.9 % (`stress --cpu 12`) |
| **`NexusCriticalMemory`** | Expresión verificada (73.7 % disponible). **No se forzó la condición**: llenar la RAM del VM de Docker puede reiniciar Docker Desktop |
| Inhibición | `NexusTargetDown` no se autoinhibe (matcher `alertname !=` confirmado) |
| Enrutamiento por severidad | `critical` y `high` entregados a `nexus-alert-sink` |

**Nota sobre `nexus_db_active_connections`:** mide las conexiones abiertas por la
aplicación hacia PostgreSQL. En reposo vale 1 (la conexión mínima del pool) y
sube hasta 5 bajo concurrencia real. Como los picos duran milisegundos y el
scrape ocurre cada 15 s, la regla opcional usa `max_over_time(...[5m]) >= 3` en
lugar de un muestreo instantáneo, que nunca alcanzaría el umbral.
