from calendar import monthrange
from datetime import date
from pathlib import Path

from fpdf import FPDF, XPos, YPos

from app.config import CONGREGACAO_NOME, CONTATO_RESPONSAVEL, PYTHON_WEEKDAY_TO_DIA_SEMANA
from app.models import DesignacaoCarrinho, DesignacaoDirigente, SlotTipo

MES_NOMES = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL", 5: "MAIO", 6: "JUNHO",
    7: "JULHO", 8: "AGOSTO", 9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
}

DIA_SEMANA_ABREV = {
    "SEGUNDA": "SEG.", "TERCA": "TER.", "QUARTA": "QUA.", "QUINTA": "QUI.",
    "SEXTA": "SEX.", "SABADO": "SÁB.", "DOMINGO": "DOM.",
}


def _nome_coluna(local: str, periodo: str, locais_com_um_so_periodo: set[str]) -> str:
    if local in locais_com_um_so_periodo:
        return local
    periodo_label = "Manhã" if periodo == "MANHA" else "Tarde"
    return f"{local} {periodo_label}"


def _colunas_a_partir_dos_slots(slots: list[SlotTipo]) -> list[tuple[str, str]]:
    """Ordena as colunas como nas listas reais: Manhã antes de Tarde, e dentro do
    mesmo período em ordem alfabética do local — não pela primeira ocorrência na
    semana (que colocaria "Segunda-Tarde" antes de "Quarta-Manhã")."""
    vistos: set[tuple[str, str]] = set()
    for slot in slots:
        periodo = slot.periodo.value if hasattr(slot.periodo, "value") else slot.periodo
        vistos.add((slot.local, periodo))
    return sorted(vistos, key=lambda c: (0 if c[1] == "MANHA" else 1, c[0]))


def _nomes_da_designacao(desig: DesignacaoCarrinho | None, pessoas_por_id: dict[int, str]) -> str:
    if desig is None:
        return ""
    nomes = [pessoas_por_id.get(pid, "?") for pid in (desig.pessoa_id_1, desig.pessoa_id_2) if pid]
    return "/".join(nomes)


def gerar_pdf_escala(
    mes_referencia: str,
    designacoes: list[DesignacaoCarrinho],
    designacoes_dirigentes: list[DesignacaoDirigente],
    slots: list[SlotTipo],
    bloqueios: list,
    pessoas_por_id: dict[int, str],
    dirigentes_por_id: dict[int, str],
    caminho_saida: Path,
    designacoes_saidas=None,
    saidas_por_id=None,
) -> Path:
    ano, mes = (int(x) for x in mes_referencia.split("-"))
    ultimo_dia = monthrange(ano, mes)[1]

    colunas = _colunas_a_partir_dos_slots(slots)
    slot_por_dia_coluna: dict[tuple[str, tuple[str, str]], str] = {}
    for slot in slots:
        chave_coluna = (slot.local, slot.periodo.value if hasattr(slot.periodo, "value") else slot.periodo)
        slot_por_dia_coluna[(slot.dia_semana, chave_coluna)] = slot.slot_id

    designacao_por_data_slot = {(d.data.isoformat(), d.slot_id): d for d in designacoes}

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 12)
    titulo = f"LISTA DO CARRINHO MÊS DE {MES_NOMES[mes]} DE {ano} {CONGREGACAO_NOME.upper()}"
    pdf.multi_cell(0, 7, titulo, align="C")
    pdf.ln(2)

    largura_data = 28
    largura_coluna = (190 - largura_data) / max(len(colunas), 1)
    col_widths = [largura_data] + [largura_coluna] * len(colunas)

    periodos_por_local: dict[str, set[str]] = {}
    for local, periodo in colunas:
        periodos_por_local.setdefault(local, set()).add(periodo)
    locais_com_um_so_periodo = {local for local, periodos in periodos_por_local.items() if len(periodos) == 1}

    pdf.set_font("helvetica", "B", 9)
    with pdf.table(col_widths=col_widths, text_align="CENTER", line_height=6) as table:
        header = table.row()
        header.cell("Data")
        for local, periodo in colunas:
            header.cell(_nome_coluna(local, periodo, locais_com_um_so_periodo))

        pdf.set_font("helvetica", "", 8)
        for dia in range(1, ultimo_dia + 1):
            data_atual = date(ano, mes, dia)
            dia_semana = PYTHON_WEEKDAY_TO_DIA_SEMANA[data_atual.weekday()]
            bloqueio = next((b for b in bloqueios if b.data_inicio <= data_atual <= b.data_fim), None)

            row = table.row()
            row.cell(f"{data_atual.strftime('%d/%m')}-{DIA_SEMANA_ABREV[dia_semana]}")

            if bloqueio:
                row.cell(bloqueio.motivo or "Sem carrinho", colspan=len(colunas))
                continue

            for chave_coluna in colunas:
                slot_id = slot_por_dia_coluna.get((dia_semana, chave_coluna))
                desig = designacao_por_data_slot.get((data_atual.isoformat(), slot_id)) if slot_id else None
                row.cell(_nomes_da_designacao(desig, pessoas_por_id))

    if designacoes_dirigentes:
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 7, "DIRIGENTES DE CAMPO À TARDE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("helvetica", "", 8)
        with pdf.table(col_widths=(30, 60), text_align="LEFT", line_height=6) as table:
            header = table.row()
            header.cell("Data")
            header.cell("Dirigente")
            for d in sorted(designacoes_dirigentes, key=lambda x: x.data):
                if d.dirigente_id is None:
                    continue
                row = table.row()
                dia_semana = PYTHON_WEEKDAY_TO_DIA_SEMANA[d.data.weekday()]
                row.cell(f"{d.data.strftime('%d/%m')}-{DIA_SEMANA_ABREV[dia_semana]}")
                row.cell(dirigentes_por_id.get(d.dirigente_id, "?"))

    if designacoes_saidas:
        rotulo_saida = saidas_por_id or {}
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 7, "SAÍDAS DE CAMPO", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("helvetica", "", 8)
        with pdf.table(col_widths=(30, 60, 60), text_align="LEFT", line_height=6) as table:
            header = table.row()
            header.cell("Data")
            header.cell("Saída")
            header.cell("Dirigente")
            for d in sorted(designacoes_saidas, key=lambda x: (x.data, x.saida_id)):
                row = table.row()
                dia_semana = PYTHON_WEEKDAY_TO_DIA_SEMANA[d.data.weekday()]
                row.cell(f"{d.data.strftime('%d/%m')}-{DIA_SEMANA_ABREV[dia_semana]}")
                row.cell(rotulo_saida.get(d.saida_id, d.saida_id))
                row.cell(pessoas_por_id.get(d.dirigente_id, "?") if d.dirigente_id else "")

    pdf.ln(6)
    pdf.set_font("helvetica", "I", 8)
    pdf.multi_cell(
        0, 5,
        "LEMBRETE: Pedimos a todos que observem com antecedência suas designações. Se for o caso, "
        "você mesmo pode arranjar um substituto, porém entre os irmãos e irmãs que participam desta "
        f"lista, e avisar o irmão {CONTATO_RESPONSAVEL}.",
    )

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(caminho_saida))
    return caminho_saida
