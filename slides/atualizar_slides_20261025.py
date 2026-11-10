"""Atualiza a apresentação de setembro (mestrado_status.pptx) com a rodada de 25/10/2026.

Mantém a formatação dos slides originais: o texto é trocado parágrafo a parágrafo usando
o primeiro parágrafo de cada nível como molde, as tabelas trocam só o texto das células, e
slides novos são clonados de um slide existente do mesmo tipo.

Uso:
  python3 atualizar_slides_20261025.py <original.pptx> <saida.pptx>
Pré-requisito: python3 gerar_figuras_20261025.py (figuras de diagnóstico).
"""

import copy
import os
import sys

from pptx import Presentation

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_GRAFICOS = os.path.join(_SCRIPT_DIR, '..', 'graficos')
_FIG = os.path.join(_SCRIPT_DIR, 'figuras_20261025')

FIG_C1 = os.path.join(_GRAFICOS, 'relatorio_compare', 'latencia_vs_instancias.png')
FIG_C2 = os.path.join(_GRAFICOS, 'relatorio_compare_lat', 'latencia_vs_instancias.png')
FIG_UES_ATIVAS = os.path.join(_GRAFICOS, 'relatorio_carga', 'ues_ativas.png')
FIG_DEMANDA = os.path.join(_GRAFICOS, 'relatorio_carga', 'demanda_cpu.png')
FIG_CONCENTRA = os.path.join(_FIG, 'ues_por_instancia.png')
FIG_SERVICE0 = os.path.join(_FIG, 'service0_congelada.png')


# ----------------------------------------------------------------- helpers
def shape_by_id(slide, shape_id):
    for sh in slide.shapes:
        if sh.shape_id == shape_id:
            return sh
    raise KeyError(f'shape {shape_id} não existe no slide')


def first_text_shape(slide, skip_title=True):
    shapes = [sh for sh in slide.shapes if sh.has_text_frame]
    return shapes[1] if skip_title else shapes[0]


def set_text(shape, items):
    """items: lista de (nível, texto) ou str (nível 0). Usa o 1º parágrafo de cada nível
    do texto original como molde de formatação."""
    tf = shape.text_frame
    moldes = {}
    for p in tf.paragraphs:
        moldes.setdefault(p.level, p._p)
    txBody = tf._txBody
    for p in list(tf.paragraphs):
        txBody.remove(p._p)
    for item in items:
        level, text = (0, item) if isinstance(item, str) else item
        molde = moldes.get(level)
        if molde is None:
            molde = moldes[max([lv for lv in moldes if lv <= level], default=min(moldes))]
        p = copy.deepcopy(molde)
        runs = p.findall('{http://schemas.openxmlformats.org/drawingml/2006/main}r')
        for r in runs[1:]:
            p.remove(r)
        txBody.append(p)
        par = tf.paragraphs[-1]
        if par.runs:
            par.runs[0].text = text
        else:
            par.add_run().text = text


def set_title(slide, text):
    set_text(slide.shapes[0], [text])


def set_cell(cell, text):
    par = cell.text_frame.paragraphs[0]
    for extra in cell.text_frame.paragraphs[1:]:
        cell.text_frame._txBody.remove(extra._p)
    if par.runs:
        par.runs[0].text = text
        for r in par.runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        par.add_run().text = text


def fill_table(table_shape, rows):
    tbl = table_shape.table
    for r_idx, row in enumerate(rows):
        for c_idx, text in enumerate(row):
            set_cell(tbl.cell(r_idx, c_idx), text)
    for tr in list(tbl._tbl.tr_lst)[len(rows):]:
        tbl._tbl.remove(tr)


def replace_picture(slide, pic, path):
    """Troca a imagem mantendo a caixa original: ajusta pela proporção e centraliza."""
    from PIL import Image
    left, top, width, height = pic.left, pic.top, pic.width, pic.height
    pic._element.getparent().remove(pic._element)
    w_px, h_px = Image.open(path).size
    scale = min(width / w_px, height / h_px)
    new_w, new_h = int(w_px * scale), int(h_px * scale)
    slide.shapes.add_picture(path, left + (width - new_w) // 2, top + (height - new_h) // 2, new_w, new_h)


def clone_slide(prs, src):
    """Clona um slide sem imagens (as imagens são adicionadas depois com replace)."""
    new = prs.slides.add_slide(src.slide_layout)
    for ph in list(new.placeholders):
        ph._element.getparent().remove(ph._element)
    for sh in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(sh._element))
    return new


def picture_of(slide):
    return next(sh for sh in slide.shapes if sh.shape_type == 13)


def reorder(prs, slides_in_order):
    sld_id_lst = prs.slides._sldIdLst
    by_slide = {id(s): el for s, el in zip(prs.slides, list(sld_id_lst))}
    elements = [by_slide[id(s)] for s in slides_in_order]
    for el in list(sld_id_lst):
        sld_id_lst.remove(el)
    for el in elements:
        sld_id_lst.append(el)


# ----------------------------------------------------------------- conteúdo
def main(src_path, out_path):
    prs = Presentation(src_path)
    s = list(prs.slides)  # s[0] = slide 1 original
    (titulo, oque, arquitetura, arquivos, fases, carga, alg_mab, alg_rr, alg_mapek,
     kpi_tab, leitura, evid1, evid2, evid3, diag, valido, proximos) = s

    # Clones feitos antes de editar os originais (copiam a formatação intacta).
    kpi2_tab = clone_slide(prs, kpi_tab)
    peso_tab = clone_slide(prs, kpi_tab)
    fig_ues_ativas = clone_slide(prs, evid1)
    fig_c2 = clone_slide(prs, evid1)
    fig_service0 = clone_slide(prs, evid1)

    # 1 — título
    set_text(shape_by_id(titulo, 85), [
        'MAB (Thompson Sampling) vs Round Robin sobre auto-scaling MAPE-K',
        'Marcelo Victor · acompanhamento de mestrado · outubro/2026',
    ])

    # 2 — do que se trata
    set_text(shape_by_id(oque, 91), [
        'Pergunta: escolher a instância MEC que atende cada UE por aprendizado reduz latência em relação a um balanceamento cego?',
        'Dois roteadores sob a MESMA carga e o MESMO auto-scaling MAPE-K (2 a 10 instâncias):',
        (1, 'MAB — Thompson Sampling, aprende qual instância entrega latência dentro do alvo'),
        (1, 'Round Robin — baseline circular, sem aprendizado'),
        'Dois cenários de 60 min no testbed (Open5GS + UERANSIM + MEC em Docker):',
        (1, 'Cenário 1 — carga fixa (UEs iguais) e MAPE-K guiado por CPU'),
        (1, 'Cenário 2 — carga variável (perfis leve/médio/pesado) e MAPE-K guiado por latência'),
        'KPIs: latência média/p50/p95/p99, violação de SLA (>200 ms), instance-minutes e mudanças de escala.',
    ])

    # 3 — arquitetura (a imagem fica)
    set_text(shape_by_id(arquitetura, 97), [
        '100 UEs (UERANSIM) → 1 gNB → Open5GS Core → MEC Platform (MEP)',
        'MEC Intelligence: recebe a UE e decide a instância (MAB ou RR)',
        'Service Registry: cataloga as instâncias VidProc ativas',
        'Pool VidProc: 2 a 10 instâncias, cada uma limitada a --cpus=0.20',
        'MAPE-K: monitora CPU (cenário 1) ou latência (cenário 2) das instâncias e escala o pool',
        'Metric Catcher: recebe /latency das UEs e /app_metrics, consulta o Prometheus e escreve o CSV que alimenta a análise',
    ])

    # 4 — arquivos
    fill_table(shape_by_id(arquivos, 104), [
        ('Componente', 'Arquivo', 'Papel'),
        ('Intelligence', 'mec_apps/mec_app_inteligence.py', 'roteia UE → instância'),
        ('MAB', 'mec_apps/mab_controller.py', 'Thompson Sampling'),
        ('Round Robin', 'mec_apps/rr_controller.py', 'baseline, mesma interface do MAB'),
        ('MAPE-K', 'mec_apps/mapeK.py', 'scale up/down por CPU ou por latência'),
        ('Catcher', 'mec_apps/mec_app_metric_catcher.py', 'agrega métricas e gera o CSV'),
        ('Instâncias', 'mec_instance_manager.py', 'cria/mata VidProc (--cpus=0.20)'),
        ('Experimento', 'testar_agora.sh + run_experiment.sh', 'zera o pool, sobe tudo e roda um cenário (60 min)'),
        ('Análise', 'graficos_compare.py + graficos_carga.py', 'KPIs, gráficos MAB vs RR e carga oferecida'),
    ])

    # 6 — carga por UE
    set_title(carga, 'Dois tipos de carga por UE')
    set_text(shape_by_id(carga, 116), [
        'Cada UE roda 2 threads contra a instância atribuída: POST /infer e GET /video contínuo (chunks de 1 KB)',
        'Carga fixa (cenário 1) — todas as UEs iguais:',
        (1, '/infer a cada 0,1–0,5 s; o servidor faz sleep de 50–200 ms (espera, quase sem CPU)'),
        (1, 'Peak (100 UEs): ~333 req/s de inferência'),
        'Carga variável (cenário 2) — cada UE tem um perfil fixo, sorteado pelo ID (o mesmo no MAB e no RR):',
        (1, 'leve (59 UEs): 1 req a cada 0,5–1,0 s, 4 ms de CPU por requisição'),
        (1, 'médio (27 UEs): 1 req a cada 0,3–0,6 s, 8 ms de CPU'),
        (1, 'pesado (14 UEs): 1 req a cada 0,2–0,4 s, 12 ms de CPU'),
        (1, 'Peak: ~185 req/s e ~1,35 s de CPU por segundo ≈ 6,8 instâncias de 0,20 core cheias'),
    ])

    # novo — UEs ativas por perfil
    set_title(fig_ues_ativas, 'Carga variável: UEs ativas por perfil')
    replace_picture(fig_ues_ativas, picture_of(fig_ues_ativas), FIG_UES_ATIVAS)
    set_text(first_text_shape(fig_ues_ativas), [
        'Mesmas 5 fases nos dois cenários. A carga foi reconstruída do log do workload e do sorteio de perfil de cada UE (100 de 100 conferidas com os logs das UEs).',
    ])

    # 10 — MAPE-K
    set_text(shape_by_id(alg_mapek, 136), [
        'a cada T_poll = 5 s:',
        '    MONITOR   m_i ← CPU (cenário 1) ou latência média (cenário 2) da instância i',
        '    ANALYZE   se (agora − t_última_ação) < T_cool (30 s): NO_ACTION',
        '              senão se max(m) > τ_up e n < N_max (10): SCALE_UP',
        '              senão se média(m) < τ_down e max(m) ≤ τ_up e n > N_min (2): SCALE_DOWN',
        '              senão: NO_ACTION',
        '    PLAN+EXEC SCALE_UP   → sobe instância e confirma no service registry',
        '              SCALE_DOWN → encerra instância via API (espera HTTP 200)',
        '    limiares  CPU: τ_up 10% / τ_down 5%   ·   latência: τ_up 100 ms / τ_down 40 ms',
    ])
    set_text(shape_by_id(alg_mapek, 137), [
        'Sobe pela instância PIOR (máximo) e desce pela MÉDIA do pool, com banda morta — sem ela o pool oscilava entre N e N−1.',
    ])

    # 11 — KPIs cenário 1
    set_title(kpi_tab, 'Cenário 1 — carga fixa, MAPE-K por CPU (25/10/2026)')
    fill_table(shape_by_id(kpi_tab, 143), [
        ('KPI', 'MAB', 'Round Robin'),
        ('Amostras / duração', '363 / 60,6 min', '364 / 60,7 min'),
        ('Latência média', '134,15 ms', '129,67 ms'),
        ('Latência p50', '131,81 ms', '129,09 ms'),
        ('Latência p95', '167,66 ms', '144,41 ms'),
        ('Latência p99', '194,17 ms', '154,93 ms'),
        ('Violação de SLA (>200 ms)', '0,83 %', '0,00 %'),
        ('CPU média', '4,50 %', '6,29 %'),
        ('Throughput médio', '69,15 kbps', '98,63 kbps'),
        ('Instâncias média / máx', '6,68 / 10', '4,69 / 7'),
        ('Instance-minutes', '405,8', '285,1'),
        ('Mudanças de escala', '24', '10'),
    ])

    # 12 — gráfico cenário 1
    set_title(evid1, 'Cenário 1 — latência e instâncias ao longo do tempo')
    replace_picture(evid1, picture_of(evid1), FIG_C1)
    set_text(shape_by_id(evid1, 157), [
        'Latência praticamente igual (~130 ms, abaixo do SLA). A diferença está no custo: com a mesma carga, o MAB sobe até 10 instâncias e o RR para em 7.',
    ])

    # 13 — leitura cenário 1
    set_title(leitura, 'Cenário 1 — leitura')
    set_text(shape_by_id(leitura, 150), [
        'A carga agora se sustenta: ramp até 100 UEs, peak e drain aparecem na CPU, nas instâncias e na latência — o problema de junho foi resolvido.',
        'Latência empatada: média de 134 ms (MAB) vs 130 ms (RR); p95 de 168 vs 144 ms.',
        'Custo e estabilidade favorecem o RR: 406 vs 285 instance-minutes (+42%) e 24 vs 10 mudanças de escala.',
        'Aqui o /infer é espera (sleep): a CPU fica baixa e não existe instância "melhor" para o MAB aprender — o espaço de ganho é pequeno por construção.',
        'Por isso o cenário 2: carga que consome CPU de verdade e MAPE-K guiado por latência.',
    ])

    # novo — KPIs cenário 2
    set_title(kpi2_tab, 'Cenário 2 — carga variável, MAPE-K por latência (25/10/2026)')
    fill_table(next(sh for sh in kpi2_tab.shapes if sh.has_table), [
        ('KPI', 'MAB', 'Round Robin'),
        ('Amostras / duração', '363 / 60,6 min', '363 / 60,6 min'),
        ('Latência média', '156,26 ms', '44,07 ms'),
        ('Latência p50', '127,32 ms', '36,51 ms'),
        ('Latência p95', '427,61 ms', '105,68 ms'),
        ('Latência p99', '610,60 ms', '253,55 ms'),
        ('Violação de SLA (>200 ms)', '33,70 %', '2,21 %'),
        ('CPU média', '6,21 %', '13,56 %'),
        ('Throughput médio', '27,29 kbps', '57,68 kbps'),
        ('Instâncias média / máx', '7,33 / 10', '6,02 / 10'),
        ('Instance-minutes', '444,9', '365,8'),
        ('Mudanças de escala', '20', '52'),
    ])
    set_text(next(sh for sh in kpi2_tab.shapes if sh.shape_type == 17), [
        'O RR vence em latência e em custo. Só perde em estabilidade: 52 mudanças de escala, oscilando entre 9 e 10 instâncias no peak.',
    ])

    # novo — gráfico cenário 2
    set_title(fig_c2, 'Cenário 2 — latência e instâncias ao longo do tempo')
    replace_picture(fig_c2, picture_of(fig_c2), FIG_C2)
    set_text(first_text_shape(fig_c2), [
        'O RR fica abaixo do limiar de 100 ms quase o tempo todo. O MAB passa do SLA durante boa parte do peak, mesmo com 10 instâncias no ar.',
    ])

    # 16 — demanda vs instâncias
    set_title(evid2, 'Demanda de CPU vs instâncias provisionadas (cenário 2)')
    replace_picture(evid2, picture_of(evid2), FIG_DEMANDA)
    set_text(shape_by_id(evid2, 164), [
        'No peak a carga pede ~6,8 instâncias. Os dois chegam a 10, e o MAB fica mais tempo lá — com latência pior. O gargalo do MAB não é falta de instância.',
    ])

    # 17 — evidência 1: concentração
    set_title(evid3, 'Evidência 1 — o MAB concentra UEs e deixa instâncias vazias')
    replace_picture(evid3, picture_of(evid3), FIG_CONCENTRA)
    set_text(shape_by_id(evid3, 171), [
        'No peak, o MAB chega a ~90 UEs numa instância enquanto 4 a 7 instâncias ficam sem nenhuma UE. O RR acompanha a divisão igual (no máximo 1,4× a média).',
    ])

    # novo — evidência 2: Service0 congelada
    set_title(fig_service0, 'Evidência 2 — uma instância trava e a métrica congela')
    replace_picture(fig_service0, picture_of(fig_service0), FIG_SERVICE0)
    set_text(first_text_shape(fig_service0), [
        'Com até 90 UEs, a Service0 bate no teto de 0,20 core e para de responder por 22 min. O sistema mantém o último valor (312 ms, "lenta mas viva") e o MAB continua mandando UEs para ela.',
    ])

    # novo — evidência 3: KPI sem peso
    set_title(peso_tab, 'Evidência 3 — a média entre instâncias esconde a concentração')
    fill_table(next(sh for sh in peso_tab.shapes if sh.has_table), [
        ('Execução · métrica', 'Média entre instâncias', 'Ponderada por UE'),
        ('MAB · cenário 1 · violação de SLA', '0,8 %', '5,2 %'),
        ('MAB · cenário 1 · p95', '168 ms', '201 ms'),
        ('RR · cenário 1 · violação de SLA', '0,0 %', '0,0 %'),
        ('MAB · cenário 2 · violação de SLA', '33,7 %', '51,4 %'),
        ('MAB · cenário 2 · p95', '428 ms', '551 ms'),
        ('RR · cenário 2 · violação de SLA', '2,2 %', '2,5 %'),
        ('RR · cenário 2 · p95', '106 ms', '110 ms'),
    ])
    set_text(next(sh for sh in peso_tab.shapes if sh.shape_type == 17), [
        'Hoje o KPI é a média simples entre instâncias: uma com 67 UEs pesa o mesmo que uma com 4. No RR as duas coincidem; no MAB a ponderada é bem pior. Para o paper: usar a ponderada.',
    ])

    # 20 — diagnóstico
    set_title(diag, 'Diagnóstico: por que o MAB perde')
    set_text(shape_by_id(diag, 177), [
        'Três efeitos que se reforçam:',
        (1, 'Concentração: uma instância que vai bem atrai UEs até saturar; as instâncias novas do MAPE-K quase não recebem UEs.'),
        (1, 'Métrica velha: instância que para de responder mantém o último valor, o MAB não a enxerga como falha e realimenta a sobrecarga.'),
        (1, 'Mapa desatualizado: instâncias com 0 UEs no mapa da inteligência e ~19% de CPU — as UEs não estão onde o MAB acha (97 amostras no mab_lat).'),
        'O MAPE-K reage à instância pior e leva o pool a 10, mas o MAB não usa as instâncias novas: mais custo, sem ganho de latência.',
        'A falha se repetiu nas duas rodadas do cenário 2 (21/10 e 25/10).',
    ])

    # 21 — resultado válido
    set_text(shape_by_id(valido, 183), [
        'Os problemas de junho estão resolvidos: a carga se sustenta pelas 5 fases, a latência não congela mais por falta de amostra (TTL) e o MAPE-K desescala no drain.',
        'Cada cenário parte do mesmo estado: o pool é recriado do zero (2 instâncias limpas) e catcher, inteligência e MAPE-K são reiniciados.',
        'Resultados finais: cenário 1 (MAB e RR) e cenário 2 com RR, todos de 25/10.',
        'RR + MAPE-K por latência atende o SLA em ~98% do tempo com ~6 instâncias em média — uma linha de base sólida.',
        'O mab_lat de 25/10 documenta um modo de falha real do MAB, útil para a discussão.',
    ])

    # 22 — próximos passos
    set_text(shape_by_id(proximos, 189), [
        '1. Expirar a métrica de uma instância que para de responder e tratá-la como falha no MAB.',
        '2. Investigar por que o mapa UE → instância diverge da carga real (redirecionamento via Redis e reaper).',
        '3. Usar latência ponderada por UE no resumo_kpi.csv e guardar a latência por requisição medida na UE em cada run.',
        '4. Rerodar o par do cenário 2 (mab_lat e rr_lat) com as correções.',
        '5. Reduzir a oscilação 9↔10 do MAPE-K por latência (banda morta ou cooldown).',
        'Pergunta: vale trocar a recompensa binária do MAB (≤ 100 ms) por uma contínua, ou penalizar a carga por instância, para evitar a concentração?',
    ])

    reorder(prs, [
        titulo, oque, arquitetura, arquivos, fases, carga, fig_ues_ativas,
        alg_mab, alg_rr, alg_mapek,
        kpi_tab, evid1, leitura,
        kpi2_tab, fig_c2, evid2,
        evid3, fig_service0, peso_tab,
        diag, valido, proximos,
    ])
    prs.save(out_path)
    print(f'ok: {out_path} ({len(prs.slides)} slides)')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Uso: python3 atualizar_slides_20261025.py <original.pptx> <saida.pptx>')
    main(sys.argv[1], sys.argv[2])
