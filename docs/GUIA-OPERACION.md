# Guía de operación — AIOps Mission Control

Guía práctica del stack de monitoreo de **NEXUS E-COMMERCE** (equipo *Sentinel Ops*).
Explica qué hace cada componente, cómo se relacionan, dónde entrar y cómo provocar
cada alerta a demanda para demostrarla.

Todos los comandos se ejecutan desde la raíz del proyecto:

```bash
cd ~/Documentos/proyects/alertas
```

---

## Índice

1. [Arquitectura: quién es quién](#1-arquitectura-quién-es-quién)
2. [Accesos](#2-accesos)
3. [A quién usas realmente](#3-a-quién-usas-realmente)
4. [Arrancar y detener el stack](#4-arrancar-y-detener-el-stack)
5. [Catálogo de alertas](#5-catálogo-de-alertas)
6. [Cómo disparar cada alerta](#6-cómo-disparar-cada-alerta)
7. [Verificar que disparó](#7-verificar-que-disparó)
8. [Limpiar después de una demo](#8-limpiar-después-de-una-demo)
9. [Receta para capturas: cinco alertas a la vez](#9-receta-para-capturas-cinco-alertas-a-la-vez)
10. [Trampas conocidas](#10-trampas-conocidas)
11. [Referencia rápida](#11-referencia-rápida)
12. [Problemas y soluciones](#12-problemas-y-soluciones)

---

## 1. Arquitectura: quién es quién

```
Node Exporter (:9100) ──┐
App NEXUS     (:8000) ──┤
                        ├──► PROMETHEUS (:9090) ──► ALERTMANAGER (:9093) ──► webhook a la app
                        │      scrape cada 15 s       agrupa / inhibe          (/alerts)
                        │      evalúa reglas 15 s     enruta por severidad
                        │
                        └──► GRAFANA (:3000)  (solo LEE de Prometheus)
```

| Componente | Qué hace | Qué **no** hace |
|---|---|---|
| **Prometheus** | Recolecta métricas cada 15 s, las almacena y **evalúa las reglas** | No notifica a nadie |
| **Alertmanager** | Recibe alertas ya disparadas, las agrupa, silencia y **enruta por severidad** | No evalúa reglas ni ve métricas |
| **Grafana** | Consulta PromQL y dibuja dashboards | **No participa en el pipeline de alertas** |
| **Node Exporter** | Expone métricas del sistema (CPU, memoria, disco, red) | No decide nada |
| **App NEXUS** | Expone latencia, errores HTTP 500 y conexiones a BD; inyecta caos a demanda | — |
| **PostgreSQL** | Base de datos simulada de la tienda | — |

### El ciclo de vida de una alerta

1. Un exporter publica métricas en su endpoint `/metrics`.
2. Prometheus hace *pull* de cada objetivo cada **15 s**.
3. Cada **15 s** evalúa todas las reglas contra esas series.
4. Si la condición se cumple, la alerta pasa a **`pending`** y arranca el temporizador del `for`.
5. Si la condición sigue cumpliéndose al terminar el `for`, pasa a **`firing`**.
6. Prometheus **empuja** la alerta a Alertmanager.
7. Alertmanager la agrupa, aplica inhibiciones y la envía al receptor (`/alerts` de la app).
8. Cuando la condición deja de cumplirse, la alerta pasa a **`resolved`** y también se notifica.

> **En una frase para el jurado:** Prometheus **vigila y decide**, Alertmanager **avisa**, Grafana **muestra**.

La fila que más se malinterpreta es Grafana: es un *lector* de Prometheus. Si lo apagas,
las alertas siguen disparando exactamente igual.

---

## 2. Accesos

| URL | Herramienta | Credenciales | Para qué |
|---|---|---|---|
| http://localhost:3000 | Grafana | `admin` / `sentinel2026` | Dashboard. La vista para el público |
| http://localhost:9090 | Prometheus | — | `/rules`, `/targets`, `/graph`, `/alerts` |
| http://localhost:9093 | Alertmanager | — | Alertas activas, historial, *silences* |
| http://localhost:8080 | App NEXUS | — | `/health`, `/api/products`, `/metrics`, `/chaos/*` |
| http://localhost:9100 | Node Exporter | — | Métricas crudas del sistema |

### Rutas útiles dentro de Prometheus

| Ruta | Qué muestra |
|---|---|
| `/rules` | **Estado de cada regla**: `inactive`, `pending` o `firing` |
| `/targets` | Qué objetivos están `UP` y desde cuándo |
| `/graph` | Consultas PromQL libres |
| `/alerts` | Alertas que Prometheus tiene activas |

---

## 3. A quién usas realmente

Depende del contexto:

**Durante la exposición** (lo que ve el jurado):

- **Grafana** de fondo, mostrando el dashboard.
- Al disparar una alerta, la señalas en **Alertmanager**: ahí se ve la severidad y el
  enrutamiento, que es justo lo que exige la Fase 4.
- **Prometheus** se abre solo para mostrar `/rules` y probar que la regla existe y
  está en `firing`.

**En operación real** (si esto fuera producción):

- El 90 % del tiempo vives en **Grafana** (ver tendencias) y **Alertmanager** (recibir avisos).
- **Prometheus** casi nunca se mira a mano; solo para depurar por qué una regla no dispara.

**Lo que nunca harías:** usar Prometheus como panel de monitoreo del día a día.
No está diseñado para eso.

---

## 4. Arrancar y detener el stack

### Arrancar

```bash
docker compose up -d
docker compose ps
```

Espera a que los seis servicios estén en `healthy` (~30 s la primera vez).

### Detener

```bash
docker compose down          # conserva los volúmenes (datos, historial)
docker compose down -v       # BORRA los datos de Postgres, Prometheus y Grafana
```

### Ver registros

```bash
docker compose logs -f prometheus      # recolección y errores de reglas
docker compose logs -f alertmanager    # enrutamiento y entregas
docker compose logs -f app             # alertas recibidas en /alerts
```

---

## 5. Catálogo de alertas

Grupo `nexus-aiops-required` — **obligatorias según la Fase 4**:

| Alerta | Expresión | `for` | Severidad |
|---|---|---|---|
| `NexusHighCpuUsage` | CPU > 90 % | 2 min | `high` |
| `NexusCriticalMemory` | memoria disponible < 10 % | 2 min | `high` |
| `NexusTargetDown` | `up == 0` | 1 min | `critical` |

Grupo `nexus-aiops-application` — **opcionales**, demuestran las métricas simuladas:

| Alerta | Expresión | `for` | Severidad |
|---|---|---|---|
| `NexusHighErrorRate` | HTTP 500 > 5/min | 2 min | `high` |
| `NexusSlowResponse` | p95 > 1.5 s | 2 min | `high` |
| `NexusDatabaseUnavailable` | `nexus_db_up == 0` | 1 min | `critical` |
| `NexusHighDatabaseConnections` | pico de conexiones ≥ 3 | 2 min | `high` |

Las opcionales viven en un grupo separado: puedes borrarlas sin tocar las obligatorias.

---

## 6. Cómo disparar cada alerta

> **Tiempo** = lo que tarda en pasar de `pending` a `firing`, no en aparecer como `pending`.

### NexusTargetDown (crítica) — la más fácil

```bash
docker compose stop node-exporter
# espera ~60 s
docker compose start node-exporter
```

Detener `node-exporter` no rompe nada más: la app y la base siguen funcionando.

> Alternativa: `docker compose stop app`. También la dispara, pero deja la aplicación
> caída y sin webhook que reciba la notificación.

### NexusHighCpuUsage (alta)

```bash
docker run --rm -d --name nexus-load polinux/stress stress --cpu 12 --timeout 300s
# espera ~2 min
docker rm -f nexus-load
```

**Usa `--cpu 12`, no 8.** El servicio `chaos-cpu` del compose usa 8 y esta máquina
tiene 12 núcleos: se queda en ~67 % y nunca cruza el 90 %. Por eso aquí se lanza a mano.

### NexusCriticalMemory (alta) — la única peligrosa

```bash
docker run --rm -d --name nexus-mem polinux/stress stress --vm 1 --vm-bytes 60% --timeout 240s
# si no alcanza, sube a 75 % en una segunda pasada
docker rm -f nexus-mem
```

Llenar la RAM del VM de Docker puede reiniciar Docker Desktop. Sube el porcentaje
**por pasos**, nunca de golpe, y no dejes el contenedor corriendo.

### NexusHighErrorRate (alta)

```bash
curl -X POST "localhost:8080/chaos/fail?count=100000"
```

Eso arma los errores, pero necesita tráfico para generar la tasa. En otra terminal:

```bash
while true; do curl -s -o /dev/null localhost:8080/api/products; sleep 0.2; done
```

En PowerShell:

```powershell
while ($true) { curl.exe -s -o NUL http://localhost:8080/api/products; Start-Sleep -Milliseconds 200 }
```

Corta con `Ctrl+C` y limpia con `curl -X POST localhost:8080/chaos/reset`.

### NexusSlowResponse (alta) — la más lenta en aparecer

```bash
curl -X POST "localhost:8080/chaos/latency?ms=2000"
# y el mismo generador de tráfico de arriba
```

Tarda **2–3 min**, no 2. Su expresión usa `rate(...[5m])`, así que la ventana de cinco
minutos todavía contiene las respuestas rápidas de antes de inyectar la latencia.

### NexusDatabaseUnavailable (crítica)

```bash
docker compose stop db
# espera ~60 s
docker compose start db
```

La app sigue arriba y sigue exponiendo `/metrics`; solo `nexus_db_up` cae a 0.

### NexusHighDatabaseConnections (alta)

```bash
seq 1 2500 | xargs -P 100 -I{} curl -s -o /dev/null -X POST localhost:8080/api/orders
```

Necesita un pico **sostenido** de concurrencia real. Se resuelve solo: el pico sale de
la ventana de 5 minutos y la alerta se enfría.

### Endpoints de caos (referencia)

| Endpoint | Efecto |
|---|---|
| `POST /chaos/fail?count=N` | Las próximas N peticiones a `/api/*` devuelven 500 |
| `POST /chaos/latency?ms=N` | Añade N milisegundos a cada petición a `/api/*` |
| `POST /chaos/reset` | Limpia todo el caos inyectado |
| `GET /health` | Estado actual del caos |

El caos **nunca** afecta a `/metrics` ni a `/health`: si lo hiciera, Prometheus marcaría
el objetivo como caído y dispararía `NexusTargetDown` por accidente.

---

## 7. Verificar que disparó

**Prometheus** → http://localhost:9090/rules

Cada regla muestra su estado:

| Estado | Significado |
|---|---|
| `inactive` | La condición no se cumple |
| `pending` | Se cumple, pero aún no pasó el `for` |
| `firing` | Disparó y ya se notificó |

**Alertmanager** → http://localhost:9093

La alerta aparece con su severidad y su receptor.

**Terminal** → la prueba de que la notificación llegó de verdad:

```bash
docker compose logs -f app | grep ALERT
```

```
ALERT NexusTargetDown severity=critical status=firing summary=Objetivo no disponible: node
ALERT NexusTargetDown severity=critical status=resolved summary=Objetivo no disponible: node
```

**Vía API**, si prefieres no abrir el navegador:

```bash
curl -s localhost:9090/api/v1/rules
curl -s localhost:9093/api/v2/alerts
```

---

## 8. Limpiar después de una demo

```bash
curl -X POST localhost:8080/chaos/reset
docker compose start node-exporter db 2>/dev/null
docker rm -f nexus-load nexus-mem 2>/dev/null
```

Y comprueba que todo volvió:

```bash
docker compose ps
curl -s localhost:9090/api/v1/rules
```

> **Truco:** en Alertmanager puedes crear un *silence* para silenciar una alerta
> mientras trabajas, sin tocar las reglas. Es la forma correcta de "apagar" una alerta
> temporalmente sin editar YAML.

---

## 9. Receta para capturas: cinco alertas a la vez

Si necesitas una captura con varias alertas disparadas simultáneamente, el orden importa.
Las alertas de disponibilidad y las de capacidad compiten entre sí: si tumbas la base de
datos primero, ya no puedes generar tráfico real.

### Secuencia

**1. Pico de conexiones** (debe ir primero, con la base de datos arriba):

```bash
seq 1 2500 | xargs -P 100 -I{} curl -s -o /dev/null -X POST localhost:8080/api/orders
```

Verifica que Prometheus lo captó:

```bash
curl -s localhost:9090/api/v1/query \
  --data-urlencode 'query=max_over_time(nexus_db_active_connections[5m])'
# debe devolver 3 o más
```

**2. Armar el caos de la aplicación:**

```bash
curl -X POST "localhost:8080/chaos/latency?ms=2000"
curl -X POST "localhost:8080/chaos/fail?count=100000"
```

**3. Generar tráfico sostenido** (otra terminal):

```bash
while true; do curl -s -o /dev/null localhost:8080/api/products; sleep 0.2; done
```

**4. Tumbar un objetivo** para la crítica de disponibilidad:

```bash
docker compose stop node-exporter
```

**5. A los ~60 s, tumbar la base de datos:**

```bash
docker compose stop db
```

### Cronología esperada

| Momento | Qué ocurre |
|---|---|
| +1 min | `NexusTargetDown` → `firing` |
| +2 min | `NexusHighErrorRate` → `firing` |
| +2 min | `NexusHighDatabaseConnections` → `firing` |
| +2,5 min | `NexusDatabaseUnavailable` → `firing` |
| +3 min | `NexusSlowResponse` → `firing` |

La ventana con las cinco encendidas dura **entre 60 y 180 segundos**: el pico de
conexiones sale de la ventana de 5 minutos y `NexusHighDatabaseConnections` se apaga sola.

`NexusHighCpuUsage` y `NexusCriticalMemory` **no se disparan** en esta receta, porque
`node-exporter` está caído y ambas reglas se alimentan de él. Es intencional.

---

## 10. Trampas conocidas

| Trampa | Por qué |
|---|---|
| **`chaos-cpu` usa 8 workers** | En una máquina de 12 núcleos llega al 67 % y nunca cruza el 90 %. Usa `--cpu 12` a mano |
| **La memoria puede tumbar Docker Desktop** | Llenar la RAM del VM es la única prueba realmente riesgosa. Sube el porcentaje por pasos |
| **`NexusSlowResponse` tarda 3 min** | Su `rate(...[5m])` mezcla respuestas rápidas previas durante cinco minutos |
| **Las alertas no se resuelven al instante** | Dependen de ventanas de `rate` y de los intervalos de agrupación de Alertmanager. Un retraso de 30–60 s es normal, no está roto |
| **El panel de conexiones se ve plano** | Los picos del pool duran milisegundos y el scrape ocurre cada 15 s. Por eso la regla usa `max_over_time` |
| **`NexusTargetDown` y la CPU compiten** | Si detienes `node-exporter`, las reglas de CPU y memoria se quedan sin datos |

---

## 11. Referencia rápida

### Puertos

| Puerto | Servicio |
|---|---|
| 3000 | Grafana |
| 8080 | App NEXUS |
| 9090 | Prometheus |
| 9093 | Alertmanager |
| 9100 | Node Exporter |

### Métricas expuestas por la app

| Métrica | Tipo | Mide |
|---|---|---|
| `nexus_app_response_time_seconds` | Histogram | Tiempo de respuesta |
| `nexus_app_http_500_total` | Counter | Errores HTTP 500 |
| `nexus_db_active_connections` | Gauge | Conexiones abiertas a la BD |
| `nexus_db_up` | Gauge | La app alcanza la BD |
| `nexus_app_http_requests_total` | Counter | Peticiones por endpoint y estado |
| `nexus_alerts_received_total` | Counter | Alertas entregadas por Alertmanager |

### Comandos esenciales

```bash
docker compose up -d                      # arrancar
docker compose ps                         # estado
docker compose down                       # detener (conserva datos)
curl -X POST localhost:8080/chaos/reset   # limpiar caos
docker compose logs -f app | grep ALERT   # ver notificaciones entregadas
```

### Validar la configuración sin arrancar

```bash
docker compose config --quiet

docker run --rm -v "$PWD/prometheus:/etc/prometheus:ro" \
  --entrypoint promtool prom/prometheus:v3.1.0 \
  check config /etc/prometheus/prometheus.yml

docker run --rm -v "$PWD/alertmanager:/cfg:ro" \
  --entrypoint amtool prom/alertmanager:v0.28.0 \
  check-config /cfg/alertmanager.yml
```

---

## 12. Problemas y soluciones

| Síntoma | Causa probable | Solución |
|---|---|---|
| `nexus-app` reinicia en bucle | La base aún no acepta conexiones | Esperar 30 s; `docker compose logs app` |
| Target `nexus-app` en `DOWN` | El contenedor no está `healthy` | `docker compose ps`, revisar `app/` |
| Grafana sin datos | Datasource no provisionado | `docker compose restart grafana` |
| Alerta en `pending` para siempre | El `for` no se completa porque la condición oscila | Revisar la métrica en `/graph` |
| Alertas no llegan | `alertmanager` no resuelve `app` | Ambos deben estar en la red `nexus-net` |
| Puerto ocupado | Otro servicio en 3000/9090/9100 | `netstat -ano \| findstr :9090` (Windows) |
| Docker sin espacio | Imágenes y volúmenes acumulados | `docker system prune` (revisar antes qué elimina) |
| Prometheus no recarga reglas | Se editó el YAML y no se recargó | `curl -X POST localhost:9090/-/reload` |

---

*Equipo Sentinel Ops — Gerencia de Tecnologías de Información, Ciclo IX (Huacho, Perú, 2026).*
