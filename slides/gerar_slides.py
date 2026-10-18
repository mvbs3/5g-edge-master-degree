"""Gera a apresentacao (.pptx) de acompanhamento do mestrado.

Pre-requisito:
    pip install python-pptx

Uso:
    python3 slides/gerar_graficos.py     # gera as figuras primeiro
    python3 slides/gerar_slides.py       # gera slides/mestrado_status.pptx

O conteudo de cada slide esta na lista SLIDES no fim do arquivo: edite o texto
la e rode de novo, ou edite o .pptx direto no PowerPoint/Keynote.
"""

import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG_DIR = os.path.join(BASE_DIR, "slides", "figuras")
OUT_PATH = os.path.join(BASE_DIR, "slides", "mestrado_status.pptx")

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
ACCENT = RGBColor(0x1F, 0x4E, 0x79)
MUTED = RGBColor(0x59, 0x59, 0x59)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def new_deck():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    return prs


def title_slide(prs, title, subtitle):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = title
    slide.placeholders[1].text = subtitle
    for para in slide.shapes.title.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(40)
            run.font.bold = True
            run.font.color.rgb = ACCENT
    return slide


def section_title(slide, text):
    slide.shapes.title.text = text
    for para in slide.shapes.title.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(30)
            run.font.bold = True
            run.font.color.rgb = ACCENT


def bullet_slide(prs, title, bullets):
    """bullets: lista de str ou (str, nivel)."""
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    section_title(slide, title)
    tf = slide.placeholders[1].text_frame
    tf.word_wrap = True
    first = True
    for item in bullets:
        text, level = item if isinstance(item, tuple) else (item, 0)
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        para.text = text
        para.level = level
        for run in para.runs:
            run.font.size = Pt(20 - 2 * level)
            if level > 0:
                run.font.color.rgb = MUTED
    return slide


def picture_slide(prs, title, image_name, caption=None):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    section_title(slide, title)
    path = os.path.join(FIG_DIR, image_name)
    if not os.path.exists(path):
        bullet = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(11), Inches(1)).text_frame
        bullet.text = f"[figura ausente: {image_name} — rode slides/gerar_graficos.py]"
        return slide
    width = Inches(11)
    left = int((SLIDE_W - width) / 2)
    slide.shapes.add_picture(path, left, Inches(1.6), width=width)
    if caption:
        box = slide.shapes.add_textbox(left, Inches(6.3), width, Inches(0.9)).text_frame
        box.word_wrap = True
        box.text = caption
        for run in box.paragraphs[0].runs:
            run.font.size = Pt(14)
            run.font.italic = True
            run.font.color.rgb = MUTED
    return slide


def table_slide(prs, title, headers, rows, col_widths=None):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    section_title(slide, title)
    n_rows, n_cols = len(rows) + 1, len(headers)
    left, top = Inches(0.9), Inches(1.7)
    width, height = Inches(11.5), Inches(0.4 + 0.35 * n_rows)
    table = slide.shapes.add_table(n_rows, n_cols, left, top, width, height).table
    if col_widths:
        for idx, frac in enumerate(col_widths):
            table.columns[idx].width = Emu(int(width * frac))
    for col, head in enumerate(headers):
        cell = table.cell(0, col)
        cell.text = head
        for para in cell.text_frame.paragraphs:
            for run in para.runs:
                run.font.size = Pt(14)
                run.font.bold = True
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(value)
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(13)
    return slide


def code_slide(prs, title, lines, note=None):
    """Pseudocodigo em fonte monoespacada."""
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    section_title(slide, title)
    box = slide.shapes.add_textbox(Inches(0.9), Inches(1.6), Inches(11.5), Inches(4.8)).text_frame
    box.word_wrap = True
    for idx, line in enumerate(lines):
        para = box.paragraphs[0] if idx == 0 else box.add_paragraph()
        para.text = line
        for run in para.runs:
            run.font.size = Pt(15)
            run.font.name = "Menlo"
    if note:
        nb = slide.shapes.add_textbox(Inches(0.9), Inches(6.5), Inches(11.5), Inches(0.7)).text_frame
        nb.word_wrap = True
        nb.text = note
        for run in nb.paragraphs[0].runs:
            run.font.size = Pt(14)
            run.font.italic = True
            run.font.color.rgb = MUTED
    return slide


# --------------------------------------------------------------------------- #
# conteudo
# --------------------------------------------------------------------------- #
def build(prs):
    title_slide(
        prs,
        "Roteamento adaptativo de UEs em MEC 5G",
        "MAB (Thompson Sampling) vs Round Robin sobre auto-scaling MAPE-K\n"
        "Marcelo Victor · acompanhamento de mestrado · setembro/2026",
    )

    bullet_slide(
        prs,
        "Do que se trata",
        [
            "Pergunta: escolher a instância MEC que atende cada UE por aprendizado "
            "reduz latência em relação a um balanceamento cego?",
            "Comparamos dois roteadores sob a MESMA carga e o MESMO auto-scaling:",
            ("MAB — Thompson Sampling, aprende qual instância entrega latência dentro do alvo", 1),
            ("Round Robin — baseline circular, sem aprendizado", 1),
            "O número de instâncias não é fixo: um laço MAPE-K escala de 2 a 10 conforme a CPU.",
            "Testbed real (não simulação): Open5GS + UERANSIM + plataforma MEC em Docker.",
            "KPIs do paper: latência média/p50/p95/p99, violação de SLA (>200 ms), "
            "instance-minutes e número de mudanças de escala.",
        ],
    )

    bullet_slide(
        prs,
        "Arquitetura do testbed",
        [
            "100 UEs (UERANSIM) → 1 gNB → Open5GS Core → MEC Platform (MEP)",
            "MEC Intelligence: recebe a UE e decide a instância (MAB ou RR)",
            "Service Registry: cataloga as instâncias VidProc ativas",
            "Pool VidProc: 2 a 10 instâncias, cada uma limitada a --cpus=0.20",
            "MAPE-K: monitora a CPU máxima entre instâncias e escala o pool",
            "Metric Catcher: recebe /latency das UEs e /app_metrics, consulta o "
            "Prometheus e escreve o CSV que alimenta a análise",
            "[substituir por arqHigh5g.png / export do drawio na versão final]",
        ],
    )

    table_slide(
        prs,
        "Onde cada coisa vive no código",
        ["Componente", "Arquivo", "Papel"],
        [
            ("Intelligence", "mec_apps/mec_app_inteligence.py", "roteia UE → instância"),
            ("MAB", "mec_apps/mab_controller.py", "Thompson Sampling"),
            ("Round Robin", "mec_apps/rr_controller.py", "baseline, mesma interface do MAB"),
            ("MAPE-K", "mec_apps/mapeK.py", "scale up/down por CPU"),
            ("Catcher", "mec_apps/mec_app_metric_catcher.py", "agrega métricas e gera o CSV"),
            ("Instâncias", "mec_instance_manager.py", "cria/mata VidProc (--cpus=0.20)"),
            ("Experimento", "run_experiment.sh", "roda um cenário completo (60 min)"),
            ("Análise", "graficos/graficos_compare.py", "KPIs e gráficos MAB vs RR"),
        ],
        col_widths=[0.18, 0.42, 0.40],
    )

    table_slide(
        prs,
        "Carga sintética: o que as UEs fazem",
        ["Fase", "Tempo", "UEs ativas"],
        [
            ("Warmup", "0–10 min", "10"),
            ("Ramp-up", "10–25 min", "10 → 100 (1 UE a cada ~10 s)"),
            ("Peak", "25–40 min", "100 sustentadas"),
            ("Drain", "40–55 min", "100 → 10"),
            ("Settle", "55–60 min", "10"),
        ],
        col_widths=[0.2, 0.3, 0.5],
    )

    bullet_slide(
        prs,
        "Carga por UE e agregado no peak",
        [
            "Cada UE roda 2 threads contra a instância atribuída:",
            ("POST /infer a cada 0,1–0,5 s, payload de 500–5000 B", 1),
            ("GET /video em streaming contínuo, chunks de 1 KB", 1),
            "Servidor simula visão computacional: sleep de 50–200 ms no /infer",
            "Por UE: ~3,3 req/s ≈ 72 kbps de uplink",
            "No peak (100 UEs): ~330 req/s de inferência + ~330 req/s de relatório "
            "de latência ao catcher ≈ 660 req/s no MEP",
            "200 conexões HTTP simultâneas e ~50 inferências em voo a qualquer instante",
        ],
    )

    code_slide(
        prs,
        "Algoritmo 1 — Roteamento MAB (Thompson Sampling)",
        [
            "para cada UE u que requisita serviço:",
            "    sincronizar braços com as instâncias ativas",
            "        braço que persiste  → mantém (α, β)",
            "        braço novo          → warm prior (média dos atuais, cap 10)",
            "",
            "    se u tinha braço anterior e há latência medida ℓ:",
            "        r ← 1 se ℓ ≤ L_ref (100 ms), senão 0",
            "        α ← α + r ;  β ← β + (1 − r)",
            "",
            "    se passaram T_dwell (30 s) ou o braço saiu do pool:",
            "        θ_a ~ Beta(α_a, β_a)  para cada braço a",
            "        a* ← argmax θ_a  →  atribui u a a*",
            "    senão: mantém u onde está",
        ],
        note="Recompensa binária: a instância é 'boa' se entregou dentro de 100 ms. "
        "O dwell de 30 s evita trocar a UE de instância a cada requisição.",
    )

    code_slide(
        prs,
        "Algoritmo 2 — Round Robin (baseline)",
        [
            "para cada UE u que requisita serviço:",
            "    se passaram T_dwell (30 s) ou o braço saiu do pool:",
            "        a* ← a[(i mod k) + 1]     # próximo na ordem cíclica",
            "        i ← i + 1",
            "        atribui u a a*",
            "    senão: mantém u onde está",
        ],
        note="Mesmo dwell e mesma interface do MAB — a única diferença é a política de escolha, "
        "para que a comparação isole o efeito do aprendizado.",
    )

    code_slide(
        prs,
        "Algoritmo 3 — Laço MAPE-K (auto-scaling)",
        [
            "a cada T_poll = 5 s:",
            "    MONITOR   c ← max(CPU_i) entre as instâncias ativas",
            "",
            "    ANALYZE   se (agora − t_última_ação) < T_cool (30 s): NO_ACTION",
            "              senão se c > τ_up (10%)  e n < N_max (10): SCALE_UP",
            "              senão se c < τ_down (5%) e n > N_min (2):  SCALE_DOWN",
            "              senão: NO_ACTION",
            "",
            "    PLAN+EXEC SCALE_UP   → sobe instância e confirma no service registry",
            "              SCALE_DOWN → encerra instância via API (espera HTTP 200)",
        ],
        note="O gatilho é a CPU MÁXIMA entre instâncias — decisão relevante para o resultado, "
        "como os próximos slides mostram.",
    )

    bullet_slide(
        prs,
        "Onde o código está hoje",
        [
            "Stack completo sobe e roda ponta a ponta: núcleo, RAN, MEP, pool MEC, "
            "intelligence, MAPE-K e catcher.",
            "Os dois roteadores estão implementados e intercambiáveis por variável de "
            "ambiente (CONTROLLER_TYPE=mab|rr), com CSV no mesmo formato.",
            "Protocolo de 60 min em 5 fases automatizado em run_experiment.sh, "
            "com arquivamento por cenário e script de comparação pronto.",
            "Os dois cenários já rodaram (18/06/2026): 60,4 min e 363 amostras cada, "
            "e o graficos_compare.py gerou o resumo_kpi.csv e as 7 figuras.",
            "Ou seja: a infraestrutura está completa. O que falta é a carga se "
            "comportar como o protocolo manda — próximos slides.",
        ],
    )

    table_slide(
        prs,
        "O que o resumo_kpi.csv trouxe (18/06/2026)",
        ["KPI", "MAB", "Round Robin"],
        [
            ("Amostras / duração", "363 / 60,4 min", "363 / 60,4 min"),
            ("Latência média", "615,16 ms", "460,25 ms"),
            ("Latência p50", "550,11 ms", "420,55 ms"),
            ("Latência p95", "1242,82 ms", "806,91 ms"),
            ("Latência p99", "1412,43 ms", "1118,10 ms"),
            ("Violação de SLA (>200 ms)", "96,67 %", "96,11 %"),
            ("CPU média", "2,14 %", "2,17 %"),
            ("Throughput médio", "7,87 kbps", "14,97 kbps"),
            ("Instâncias média / máx", "9,46 / 10", "9,43 / 10"),
            ("Instance-minutes", "572,2", "570,4"),
            ("Mudanças de escala", "8", "8"),
        ],
        col_widths=[0.4, 0.3, 0.3],
    )

    bullet_slide(
        prs,
        "Lendo a tabela: por que ela ainda não responde a pergunta",
        [
            "À primeira vista o Round Robin ganha: 460 ms contra 615 ms de média, "
            "p95 de 807 contra 1243.",
            "Mas os p50 (550,11 e 420,55) são exatamente os valores em que cada curva "
            "congela — ou seja, mais da metade das amostras é o mesmo número repetido.",
            "A violação de SLA de ~96% nos dois cenários é consequência disso: o valor "
            "travado está acima de 200 ms e domina a série.",
            "Os KPIs de custo e estabilidade ficaram empatados (572 contra 570 "
            "instance-minutes, 8 mudanças de escala nos dois) porque o pool foi para o "
            "teto e ficou lá nos dois casos.",
            "Conclusão: o experimento rodou, a coleta funcionou, mas a comparação "
            "MAB vs RR ainda não é válida.",
        ],
    )

    picture_slide(
        prs,
        "Evidência 1 — a latência congela no minuto 14",
        "comp_latencia.png",
        "Os primeiros 14 minutos têm dinâmica real (120 ms subindo a 1400 ms). Depois, "
        "46 minutos de linha reta: MAB em 550 ms e RR em 420 ms, sem variação nenhuma.",
    )

    picture_slide(
        prs,
        "Evidência 2 — a carga desaparece no minuto 7",
        "comp_cpu.png",
        "A CPU média sobe a ~7% nos dois primeiros minutos, decai e fica em ~2% pelo "
        "resto da execução. Se as fases de ramp e peak (10 a 40 min, até 100 UEs) "
        "tivessem acontecido, a CPU teria subido, não caído.",
    )

    picture_slide(
        prs,
        "Evidência 3 — o pool sobe e nunca desce",
        "comp_instancias.png",
        "2 para 10 instâncias em ~7 min, idêntico nos dois cenários, e 53 minutos "
        "pregado no teto. O MAPE-K decide pela CPU MÁXIMA, que fica na cota de 0.20 "
        "core, e não pela média de 2% do gráfico anterior.",
    )

    bullet_slide(
        prs,
        "Diagnóstico: uma causa explica as três evidências",
        [
            "A carga não se sustenta além dos primeiros minutos. Sem requisição "
            "chegando, três coisas acontecem juntas:",
            ("a CPU cai para o ociosidade (~2%)", 1),
            ("nenhuma amostra nova de latência chega, e o último valor por tópico "
             "persiste — daí a linha reta", 1),
            ("o MAPE-K não desescala, porque a CPU máxima continua colada na cota "
             "de 0.20 core e nunca cruza o τ_down de 5%", 1),
            "Duas hipóteses para a carga: o gerador de UEs morre (o run_workload.sh no "
            "container nr_ue) ou o ramp nunca acontece de fato.",
            "Como separar as duas: contar UEs ativas ao longo do tempo (o "
            "ues_json já está no CSV) e comparar com o cronograma das 5 fases.",
        ],
    )

    bullet_slide(
        prs,
        "O que já é resultado válido",
        [
            "A infraestrutura inteira funciona de ponta a ponta e de forma repetível: "
            "dois cenários de 60 min, mesma carga nominal, coleta idêntica.",
            "Os dois roteadores são de fato intercambiáveis sem alterar mais nada — "
            "condição necessária para a comparação ser justa.",
            "Os primeiros ~7 minutos de cada execução contêm dados reais e mostram a "
            "subida de latência sob carga crescente.",
            "O custo computacional dos dois é equivalente por construção: nas duas "
            "execuções o pool saturou igual, o que isola o roteamento como única "
            "variável quando a carga for corrigida.",
        ],
    )

    bullet_slide(
        prs,
        "Próximos passos",
        [
            "1. Instrumentar a carga: contar UEs ativas por minuto e confirmar se o "
            "ramp até 100 acontece. É o que destrava tudo o resto.",
            "2. Corrigir a agregação de latência para janela deslizante com percentis, "
            "de modo que a ausência de amostra apareça como lacuna e não como platô.",
            "3. Normalizar a CPU pela cota do container (0.20 core) antes de aplicar "
            "τ_up e τ_down, ou trocar o gatilho do MAPE-K para latência/fila.",
            "4. Repetir os dois cenários e refazer o resumo_kpi.csv — a partir daí a "
            "comparação MAB vs RR passa a ter significado.",
            "5. Verificar o cenário RR (latência não capturada e streamings residuais "
            "no início), relatado em 11/06.",
            "Pergunta para o professor: com o container limitado a 0.20 core, faz "
            "sentido manter a CPU como gatilho do MAPE-K, ou o experimento fica mais "
            "defensável escalando por latência, que é a métrica do SLA?",
        ],
    )


def main():
    prs = new_deck()
    build(prs)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    prs.save(OUT_PATH)
    print("gerado:", OUT_PATH)
    print("slides:", len(prs.slides))


if __name__ == "__main__":
    main()
