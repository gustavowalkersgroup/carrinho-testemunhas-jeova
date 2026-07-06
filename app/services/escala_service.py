import sqlite3
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app import i18n
from app.config import ESCALAS_DIR, JANELA_MESES_EVITAR_REPETIR_DUPLA
from app.engine import validators
from app.engine.calendar_utils import gerar_instancias, gerar_instancias_saida
from app.engine.sorteio import ContextoSorteio, gerar_escala, gerar_saidas
from app.models import Aviso, EscalaMensal
from app.repositories import (
    bloqueios_repo,
    dirigentes_repo,
    disponibilidades_repo,
    fixos_repo,
    historico_repo,
    pessoas_repo,
    saida_repo,
    slots_repo,
)


def mes_referencia_str(ano: int, mes: int) -> str:
    return f"{ano:04d}-{mes:02d}"


def _subtrair_meses(d: date, meses: int) -> date:
    mes_total = d.month - 1 - meses
    ano = d.year + mes_total // 12
    mes = mes_total % 12 + 1
    return date(ano, mes, 1)


def _montar_contexto(conn: sqlite3.Connection, referencia: date):
    pessoas = pessoas_repo.listar(conn)
    slots = slots_repo.listar_vigentes_no_mes(conn, referencia)
    fixos = fixos_repo.listar_vigentes_no_mes(conn, referencia)
    dirigentes = dirigentes_repo.listar(conn)

    avisos_pre = validators.validar_pool_minimo(pessoas) + validators.validar_template_slots(slots)

    data_limite_duplas = _subtrair_meses(referencia, JANELA_MESES_EVITAR_REPETIR_DUPLA)

    fixos_por_slot: dict[str, tuple[int, int | None]] = {
        f.slot_id: (f.pessoa_id_1, f.pessoa_id_2) for f in fixos
    }

    # apenas pessoas que TÊM cônjuge entram no mapa (NULL = sem cônjuge)
    conjuge_de = {p.id: p.conjuge_id for p in pessoas if getattr(p, "conjuge_id", None)}

    ctx = ContextoSorteio(
        genero_por_pessoa={p.id: p.genero.value for p in pessoas},
        ativos={p.id for p in pessoas if p.ativo},
        disponibilidade_slot=disponibilidades_repo.mapa_slot_para_pessoas(conn),
        fixos_por_slot=fixos_por_slot,
        conjuge_de=conjuge_de,
        ultima_designacao=historico_repo.ultima_designacao_por_pessoa(conn),
        total_designacoes=historico_repo.total_designacoes_por_pessoa(conn),
        duplas_recentes=historico_repo.duplas_recentes(conn, data_limite_duplas),
        dirigentes_ativos={d.id for d in dirigentes if d.ativo},
        disponibilidade_dirigente_slot=dirigentes_repo.mapa_slot_para_dirigentes(conn),
        ultima_designacao_dirigente=historico_repo.ultima_designacao_por_dirigente(conn),
        total_designacoes_dirigente=historico_repo.total_designacoes_por_dirigente(conn),
        # === saída de campo (modelo novo): dirigente É uma pessoa ===
        dirigentes_pool={p.id for p in pessoas_repo.listar_dirigentes(conn, somente_ativos=True)},
        disponibilidade_saida=saida_repo.mapa_saida_para_dirigentes(conn),
        ultima_saida=historico_repo.ultima_saida_por_dirigente(conn),
        total_saidas=historico_repo.total_saidas_por_dirigente(conn),
    )
    return ctx, avisos_pre, slots


def gerar_rascunho(conn: sqlite3.Connection, ano: int, mes: int, hoje: date) -> EscalaMensal:
    referencia = date(ano, mes, 1)
    mes_referencia = mes_referencia_str(ano, mes)

    ctx, avisos_pre, slots = _montar_contexto(conn, referencia)

    ultimo_dia = monthrange(ano, mes)[1]
    bloqueios = bloqueios_repo.listar_ativos_no_periodo(conn, referencia, date(ano, mes, ultimo_dia))

    # Saída de campo ANTES do carrinho: produz o mapa de bloqueio dirigente↔carrinho.
    saidas_vigentes = saida_repo.listar_vigentes_no_mes(conn, referencia)
    instancias_saida = gerar_instancias_saida(ano, mes, saidas_vigentes, bloqueios)
    designacoes_saidas, bloqueio_carrinho, avisos_saida = gerar_saidas(
        instancias_saida, ctx, mes_referencia, hoje
    )

    instancias = gerar_instancias(ano, mes, slots, bloqueios)
    resultado = gerar_escala(instancias, ctx, mes_referencia, hoje, bloqueio_carrinho=bloqueio_carrinho)

    historico_repo.deletar_rascunho_do_mes(conn, mes_referencia)
    historico_repo.deletar_rascunho_saidas_do_mes(conn, mes_referencia)
    if resultado.designacoes:
        historico_repo.inserir_lote(conn, resultado.designacoes)
    if designacoes_saidas:
        historico_repo.inserir_lote_saidas(conn, designacoes_saidas)

    avisos = [
        Aviso(nivel="atencao", mensagem=i18n.t(i18n.IDIOMA_PADRAO, chave), chave=chave)
        for chave in avisos_pre
    ] + avisos_saida + resultado.avisos
    return EscalaMensal(
        mes_referencia=mes_referencia,
        designacoes=historico_repo.buscar_por_mes(conn, mes_referencia),
        designacoes_dirigentes=[],
        designacoes_saidas=historico_repo.buscar_saidas_por_mes(conn, mes_referencia),
        avisos=avisos,
    )


def obter_escala(conn: sqlite3.Connection, mes_referencia: str) -> EscalaMensal:
    return EscalaMensal(
        mes_referencia=mes_referencia,
        designacoes=historico_repo.buscar_por_mes(conn, mes_referencia),
        designacoes_dirigentes=[],
        designacoes_saidas=historico_repo.buscar_saidas_por_mes(conn, mes_referencia),
        avisos=[],
    )


@dataclass
class DadosPdf:
    """Tudo que gerar_pdf_escala precisa + o caminho de saída do PDF.

    Centraliza a agregação que antes estava duplicada em
    app/web/routes.py::exportar_pdf e app/api/escalas.py::exportar_pdf.
    Os campos estão na ORDEM em que gerar_pdf_escala os recebe
    posicionalmente (mes_referencia, designacoes, designacoes_dirigentes,
    slots, bloqueios, pessoas_por_id, dirigentes_por_id, caminho), então as
    rotas podem repassar direto sem reordenar.
    """
    mes_referencia: str
    designacoes: list
    designacoes_dirigentes: list
    slots: list
    bloqueios: list
    pessoas_por_id: dict[int, str]
    dirigentes_por_id: dict[int, str]
    caminho: Path
    # === saída de campo (modelo novo) — campos NOVOS ao FIM p/ preservar ordem ===
    designacoes_saidas: list = field(default_factory=list)
    # saida_id -> label 'DiaSemana - Periodo [- local]'
    saidas_por_id: dict[str, str] = field(default_factory=dict)


def montar_dados_pdf(conn: sqlite3.Connection, ano: int, mes: int) -> DadosPdf:
    """Agrega tudo que o PDF da escala precisa para um dado (ano, mes).

    NÃO gera o PDF — apenas monta os dados e o caminho de saída
    (ESCALAS_DIR/CARRINHO_{mes_referencia}.pdf). Quem chama (rotas web/api)
    passa o resultado para gerar_pdf_escala.
    """
    mes_referencia = mes_referencia_str(ano, mes)
    referencia = date(ano, mes, 1)

    escala = obter_escala(conn, mes_referencia)
    slots = slots_repo.listar_vigentes_no_mes(conn, referencia)
    ultimo_dia = monthrange(ano, mes)[1]
    bloqueios = bloqueios_repo.listar_ativos_no_periodo(conn, referencia, date(ano, mes, ultimo_dia))
    pessoas_por_id = {p.id: p.nome for p in pessoas_repo.listar(conn)}
    dirigentes_por_id = {d.id: d.nome for d in dirigentes_repo.listar(conn)}

    # saída de campo: label por saida_id = 'DiaSemana - Periodo [- local]'
    saidas_vigentes = saida_repo.listar_vigentes_no_mes(conn, referencia)
    saidas_por_id: dict[str, str] = {}
    for s in saidas_vigentes:
        periodo = getattr(s.periodo, "value", s.periodo)
        label = f"{s.dia_semana} - {periodo}"
        if getattr(s, "local", ""):
            label += f" - {s.local}"
        saidas_por_id[s.saida_id] = label

    caminho = ESCALAS_DIR / f"CARRINHO_{mes_referencia}.pdf"

    return DadosPdf(
        mes_referencia=mes_referencia,
        designacoes=escala.designacoes,
        designacoes_dirigentes=escala.designacoes_dirigentes,
        slots=slots,
        bloqueios=bloqueios,
        pessoas_por_id=pessoas_por_id,
        dirigentes_por_id=dirigentes_por_id,
        caminho=caminho,
        designacoes_saidas=historico_repo.buscar_saidas_por_mes(conn, mes_referencia),
        saidas_por_id=saidas_por_id,
    )


def editar_designacao(conn: sqlite3.Connection, designacao_id: int, pessoa_id_1: int | None, pessoa_id_2: int | None) -> bool:
    return historico_repo.atualizar_designacao(conn, designacao_id, pessoa_id_1, pessoa_id_2)


def editar_designacao_dirigente(conn: sqlite3.Connection, designacao_id: int, dirigente_id: int | None) -> bool:
    return historico_repo.atualizar_designacao_dirigente(conn, designacao_id, dirigente_id)


def editar_designacao_saida(conn: sqlite3.Connection, designacao_id: int, dirigente_id: int | None) -> bool:
    return historico_repo.atualizar_designacao_saida(conn, designacao_id, dirigente_id)


def fechar_mes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    historico_repo.fechar_mes(conn, mes_referencia)
    historico_repo.fechar_mes_saidas(conn, mes_referencia)
