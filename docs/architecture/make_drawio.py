"""Generates docs/architecture/backend.drawio (two pages: actual / propuesta).

    python docs/architecture/make_drawio.py

Kept as code so the diagram changes in the same commit as the architecture.
Open the output in https://app.diagrams.net or the draw.io desktop app.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_name("backend.drawio")

AWS = "#232F3E"
STYLE = {
    "phone": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;",
    "lambda": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;",
    "store": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=10;fillColor=#d5e8d4;strokeColor=#82b366;",
    "s3": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=10;fillColor=#f8cecc;strokeColor=#b85450;",
    "ext": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;dashed=1;",
    "ops": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;",
    "gw": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;",
    "stage": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#d79b00;fontSize=10;",
    "sentinel": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#b85450;dashed=1;fontSize=10;",
    "group": "rounded=1;whiteSpace=wrap;html=1;fillColor=none;strokeColor=" + AWS + ";dashed=1;verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;",
    "worker_group": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff8ee;strokeColor=#d79b00;verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;",
    "issue": "shape=note;whiteSpace=wrap;html=1;size=12;fillColor=#f8cecc;strokeColor=#b85450;fontSize=10;align=left;spacingLeft=4;",
    "good": "shape=note;whiteSpace=wrap;html=1;size=12;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;align=left;spacingLeft=4;",
    "new": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#2d7600;strokeWidth=2;",
    "title": "text;html=1;fontSize=18;fontStyle=1;align=left;",
}
EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=10;endArrow=block;"
EDGE_DASH = EDGE + "dashed=1;"


class Page:
    def __init__(self, name: str):
        self.name, self.cells, self.n = name, [], 2

    def _id(self) -> str:
        self.n += 1
        return f"c{self.n}"

    def box(self, label, x, y, w, h, kind, parent="1") -> str:
        i = self._id()
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(label, {chr(34): "&quot;"})}" style="{STYLE[kind]}" '
            f'vertex="1" parent="{parent}"><mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/></mxCell>')
        return i

    def edge(self, a, b, label="", dashed=False, color=None) -> str:
        i = self._id()
        style = (EDGE_DASH if dashed else EDGE) + (f"strokeColor={color};fontColor={color};" if color else "")
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" edge="1" '
            f'parent="1" source="{a}" target="{b}"><mxGeometry relative="1" as="geometry"/></mxCell>')
        return i

    def xml(self) -> str:
        body = "".join(self.cells)
        return (f'<diagram name="{self.name}" id="{self.name}"><mxGraphModel dx="1600" dy="1000" '
                f'grid="1" gridSize="10" guides="1" page="1" pageScale="1" pageWidth="1900" '
                f'pageHeight="1250" math="0" shadow="0"><root><mxCell id="0"/>'
                f'<mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram>')


def pipeline(p: Page, x: int, y: int, sentinels: bool) -> str:
    """The worker and the barra stages inside it. Returns the group id."""
    g = p.box("WorkerFunction · contenedor (ECR) · 3 GB · 10 min<br>server/api/handler.worker → process.process_job → barra",
              x, y, 560, 330, "worker_group")
    stages = ["1 probe<br>(fps, frames)", "2 pose<br>MediaPipe (T,17,3)", "3 classify<br>geometría + modelo",
              "4 fusion<br>+ voto visión", "5 segment<br>reps (s,t,e)", "6 checks / faults<br>reglas por rep",
              "7 score<br>0–100 / None", "8 informe<br>(LLM o fallback)", "9 nota visión<br>(consultiva)"]
    for k, label in enumerate(stages):
        col, row = k % 5, k // 5
        p.box(label, x + 15 + col * 108, y + 50 + row * 120, 98, 52, "stage")
        if sentinels:
            p.box("centinela", x + 25 + col * 108, y + 106 + row * 120, 78, 20, "sentinel")
    p.box("payload → Jobs.result · traza → Traces", x + 15, y + 285, 300, 30, "stage")
    return g


def actual() -> Page:
    p = Page("Actual (2026-10-11)")
    p.box("barrapp · backend actual (stack sam-app, eu-west-1)", 20, 10, 900, 30, "title")
    phone = p.box("App Android<br>(Kotlin · com.fitness.barrapp)<br><i>Coach local, sin backend</i>", 30, 330, 170, 90, "phone")

    aws = p.box("AWS · stack sam-app", 260, 60, 1240, 1040, "group")
    gw = p.box("API Gateway (HTTP API)<br><i>sin throttling</i>", 300, 340, 160, 70, "gw")
    cognito = p.box("Cognito User Pool<br>(cuentas, JWT)", 300, 150, 160, 60, "ops")
    api = p.box("ApiFunction (zip · 512 MB · 30 s)<br>server/api/handler.api<br>/v1/jobs · upload · submit · history<br>/v1/chat · feedback · referral · auth",
                520, 320, 230, 110, "lambda")
    s3 = p.box("S3 videobucket<br>{owner}/{job}.mp4<br>caducidad 30 días", 820, 120, 160, 90, "s3")
    jobs = p.box("DynamoDB Jobs<br>(status, stage, result)", 820, 300, 160, 70, "store")
    uploads = p.box("DynamoDB Uploads<br>(log de subida)", 1010, 300, 150, 70, "store")
    traces = p.box("DynamoDB Traces<br>(traza por job, TTL)", 1010, 400, 150, 70, "store")
    fb = p.box("DynamoDB Feedback<br>+ Referrals", 820, 400, 160, 70, "store")
    secret = p.box("Secrets Manager<br>barrapp/nan-api-key", 1210, 120, 160, 60, "ops")
    worker = pipeline(p, 520, 560, sentinels=True)
    sweeper = p.box("SweeperFunction<br>EventBridge cada 15 min<br>cierra jobs y subidas atascados", 300, 560, 180, 80, "lambda")
    dlq = p.box("SQS WorkerDLQ", 1210, 600, 150, 50, "ops")
    alarms = p.box("CloudWatch alarms<br>(DLQ > 0, Errors > 2)<br>→ SNS email", 1210, 690, 150, 70, "ops")
    logs = p.box("CloudWatch Logs<br>[barra] … líneas", 1210, 790, 150, 50, "ops")
    nan = p.box("nan.builders (externo, OpenAI-compatible)<br>mimo-v2.6-flash · visión<br>qwen3.8-flash · chat objetivos<br>deepseek-v4-flash · informe",
                1560, 520, 230, 100, "ext")
    deepseek = p.box("api.deepseek.com<br><i>clave vacía → nunca se usa</i>", 1560, 680, 230, 50, "ext")

    p.edge(phone, gw, "① POST /v1/jobs<br>⑨ GET /v1/jobs (polling)")
    p.edge(phone, s3, "② subida multiparte<br>con URLs prefirmadas", dashed=True)
    p.edge(gw, api, "")
    p.edge(api, cognito, "verifica JWT", dashed=True)
    p.edge(api, jobs, "crea / lee")
    p.edge(api, uploads, "")
    p.edge(api, fb, "")
    p.edge(api, worker, "③ submit → ④ Lambda invoke async")
    p.edge(worker, s3, "⑤ descarga clip<br>sube recorte", dashed=True)
    p.edge(worker, jobs, "⑧ result (1 item)")
    p.edge(worker, traces, "traza")
    p.edge(worker, nan, "⑥ localizar · ⑦ nota / 2ª opinión / conteo")
    p.edge(worker, secret, "clave NaN", dashed=True)
    p.edge(api, nan, "/v1/chat")
    p.edge(worker, deepseek, "informe", dashed=True, color="#b85450")
    p.edge(worker, dlq, "fallo tras 2 reintentos", dashed=True)
    p.edge(dlq, alarms, "")
    p.edge(sweeper, jobs, "reap")
    p.edge(sweeper, s3, "aborta multipart", dashed=True)

    issues = [
        ("D1 mimo-v2.5 retirado → visión muda desde 17‑09; el 401 se tragaba como «respuesta vacía»", 1560, 120),
        ("Worker vive dentro del módulo de la API: importa referral/auth y sus tablas → 2 caídas por imports (12‑09 y la que iba a venir)", 1560, 200),
        ("Result entero en 1 item DynamoDB (~3,7 KB/rep; máx. 400 KB) → una serie de ~100 reps no se puede guardar", 1560, 290),
        ("Sin staging: cada deploy va directo a producción", 1560, 370),
        ("Dos clientes LLM (vision.py, chat.py) + deepseek.py muerto", 1560, 440),
        ("Texto visible en inglés (D3) · commit «unknown» (D7, ya arreglado en código)", 1560, 760),
        ("Identidad anónima = X-Device-Id; sin throttling en la API", 1560, 830),
    ]
    for text, x, y in issues:
        p.box(text, x, y, 230, 62, "issue")
    goods = [
        ("Bien: subida directa móvil→S3, multiparte reanudable", 30, 470),
        ("Bien: worker async + DLQ + alarmas + sweeper", 30, 545),
        ("Bien: el LLM nunca pisa la medida; traza por job", 30, 620),
    ]
    for text, x, y in goods:
        p.box(text, x, y, 200, 55, "good")
    return p


def propuesta() -> Page:
    p = Page("Propuesta")
    p.box("barrapp · backend propuesto (mismo serverless, menos acoplado)", 20, 10, 1100, 30, "title")
    phone = p.box("App Android<br>(todo en español)", 30, 330, 170, 80, "phone")
    aws = p.box("AWS · stacks sam-app-staging y sam-app (mismo template)", 260, 60, 1240, 1040, "group")
    gw = p.box("API Gateway (HTTP API)<br>+ throttling por ruta", 300, 340, 160, 70, "gw")
    api = p.box("ApiFunction<br>api/handler.py (solo HTTP)", 520, 340, 200, 70, "lambda")
    s3 = p.box("S3 videobucket<br>clips + results/{job}.json", 820, 120, 170, 80, "s3")
    jobs = p.box("DynamoDB Jobs<br>status + resumen + puntero a S3", 820, 300, 170, 70, "store")
    traces = p.box("DynamoDB Traces<br>(+ entradas «sentinel»)", 1020, 300, 160, 70, "store")
    queue = p.box("SQS JobsQueue<br>(visible, reintentos,<br>concurrencia reservada)", 520, 470, 200, 70, "new")
    worker = pipeline(p, 520, 590, sentinels=True)
    p.box("worker.py: entrada propia del worker; no importa nada de la API", 820, 470, 200, 55, "new")
    llm = p.box("server/llm.py<br>cliente único NaN<br>(errores con causa, modelo registrado,<br>comprobación de /v1/models)", 1210, 560, 190, 100, "new")
    i18n = p.box("barra/i18n.py<br>code + texto en español", 1210, 690, 190, 55, "new")
    contracts = p.box("barra/contracts.py + sentinel.py<br>contrato por etapa", 1210, 770, 190, 55, "new")
    nan = p.box("nan.builders<br>mimo-v2.6-flash · deepseek-v4-flash · qwen3.8-flash", 1560, 570, 230, 80, "ext")
    metrics = p.box("CloudWatch: métricas por versión<br>SentinelViolation · VisionCallFailed<br>ZeroRepRate → SNS", 1210, 870, 190, 80, "new")
    canary = p.box("Clips centinela (canario)<br>tras cada deploy: staging → prod<br>rollback si cambia un resultado", 820, 960, 260, 70, "new")

    p.edge(phone, gw, "API")
    p.edge(phone, s3, "subida multiparte", dashed=True)
    p.edge(gw, api, "")
    p.edge(api, jobs, "")
    p.edge(api, queue, "submit → mensaje")
    p.edge(queue, worker, "consume")
    p.edge(worker, s3, "result JSON completo")
    p.edge(worker, jobs, "resumen + puntero")
    p.edge(worker, traces, "traza + centinelas")
    p.edge(worker, llm, "")
    p.edge(llm, nan, "")
    p.edge(worker, metrics, "log → metric filter", dashed=True)
    p.edge(canary, worker, "", dashed=True)
    return p


def main() -> None:
    pages = [actual(), propuesta()]
    xml = ('<?xml version="1.0" encoding="UTF-8"?><mxfile host="app.diagrams.net" '
           'type="device">' + "".join(pg.xml() for pg in pages) + "</mxfile>")
    OUT.write_text(xml)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
