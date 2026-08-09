"""Importa um histórico de designações (carrinho) numa congregação: cadastra
pessoas, define disponibilidades e aplica fixos de alta confiança.

Deliberadamente SEM dados de nenhuma pessoa real: quem usa isto entra com o
histórico (nomes, gêneros, slots) na hora, via `importar_historico(conn,
dados)`. Dados reais de uma congregação específica NUNCA vão para o
repositório — ver `.gitignore` (`scripts/seed_dados_reais.py`) e a rota
`POST /admin/importar-historico` (`app/web/admin_routes.py`), que recebe o
histórico no corpo da requisição em vez de embuti-lo no código.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Sequence

from app.models import FixoIn, PessoaIn
from app.repositories import pessoas_repo
from app.services import cadastro_service

FIXO_FRACAO_MINIMA_PADRAO = 0.75
FIXO_MESES_MINIMOS_PADRAO = 4


def _construir_disponibilidades(historico: Sequence[Sequence[Any]]) -> dict[str, set[str]]:
    slots_por_pessoa: dict[str, set[str]] = defaultdict(set)
    for _mes, slot_id, pessoas in historico:
        for nome in pessoas:
            slots_por_pessoa[nome].add(slot_id)
    return slots_por_pessoa


def _detectar_fixos(
    historico: Sequence[Sequence[Any]], fracao_minima: float, meses_minimos: int
) -> list[tuple[str, str, float, int]]:
    """Para cada slot_id, calcula a fração de ocorrências em que cada pessoa
    aparece e em quantos meses distintos ela aparece. Retorna candidatos que
    atingem os limiares informados."""
    ocorrencias_por_slot: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    for mes, slot_id, pessoas in historico:
        ocorrencias_por_slot[slot_id].append((mes, set(pessoas)))

    candidatos = []
    for slot_id, ocorrencias in ocorrencias_por_slot.items():
        total = len(ocorrencias)
        contagem: dict[str, int] = defaultdict(int)
        meses_por_pessoa: dict[str, set[str]] = defaultdict(set)
        for mes, pessoas in ocorrencias:
            for nome in pessoas:
                contagem[nome] += 1
                meses_por_pessoa[nome].add(mes)
        for nome, qtd in contagem.items():
            fracao = qtd / total
            n_meses = len(meses_por_pessoa[nome])
            if fracao >= fracao_minima and n_meses >= meses_minimos:
                candidatos.append((slot_id, nome, fracao, n_meses))
    candidatos.sort(key=lambda c: (c[0], -c[2]))
    return candidatos


def _ultimo_mes_por_pessoa(historico: Sequence[Sequence[Any]]) -> dict[str, str]:
    ultimo: dict[str, str] = {}
    for mes, _slot_id, pessoas in historico:
        for nome in pessoas:
            if nome not in ultimo or mes > ultimo[nome]:
                ultimo[nome] = mes
    return ultimo


def _vincular_dirigentes(conn, dirigentes_pool: Sequence[str], pessoas_existentes: dict) -> list[tuple[str, str]]:
    """Casa cada nome do pool de dirigentes contra as pessoas já cadastradas
    pelo primeiro nome (mesma pessoa podendo aparecer com ou sem sobrenome em
    fontes diferentes). O modelo atual é "dirigente É uma pessoa"
    (`pessoas.pode_dirigir`, ver `app/db/migrations.py:_migrar_dirigentes_para_pessoas`),
    então isto marca a pessoa existente em vez de duplicar."""
    pessoas_por_primeiro: dict[str, list] = defaultdict(list)
    for pessoa in pessoas_existentes.values():
        pessoas_por_primeiro[pessoa.nome.split()[0].strip().lower()].append(pessoa)

    resultado: list[tuple[str, str]] = []
    for nome_completo in dirigentes_pool:
        primeiro = nome_completo.split()[0].strip().lower()
        candidatos = pessoas_por_primeiro.get(primeiro, [])
        if len(candidatos) == 1:
            pessoa = candidatos[0]
            if pessoa.pode_dirigir:
                resultado.append((nome_completo, f"já vinculado ({pessoa.nome})"))
                continue
            dados = pessoa.model_dump(exclude={"id"})
            dados["pode_dirigir"] = True
            pessoas_repo.atualizar(conn, pessoa.id, PessoaIn(**dados))
            resultado.append((nome_completo, f"vinculado à pessoa existente ({pessoa.nome})"))
        elif len(candidatos) > 1:
            resultado.append((
                nome_completo,
                f"AMBÍGUO: {len(candidatos)} pessoas com o primeiro nome "
                f"'{primeiro}' — não vinculado, revise manualmente",
            ))
        else:
            nova = pessoas_repo.criar(conn, PessoaIn(nome=nome_completo, genero="M", pode_dirigir=True))
            pessoas_por_primeiro[primeiro].append(nova)
            resultado.append((nome_completo, "pessoa nova criada"))
    return resultado


def importar_historico(
    conn,
    *,
    historico: Sequence[Sequence[Any]],
    genero: dict[str, str],
    genero_incerto: dict[str, str] | None = None,
    dirigentes_pool: Sequence[str] | None = None,
    fixo_fracao_minima: float = FIXO_FRACAO_MINIMA_PADRAO,
    fixo_meses_minimos: int = FIXO_MESES_MINIMOS_PADRAO,
    vigencia_inicio_fixos: date | None = None,
    mes_limite_inativos: str | None = None,
) -> dict:
    """Cadastra pessoas, define disponibilidades e aplica fixos de alta
    confiança a partir de um histórico de designações. Roda numa conexão já
    aberta (SQLite local OU Postgres/web, com a congregação certa já
    declarada por quem chamou). Idempotente: pode ser chamada várias vezes
    sem duplicar nada.

    `historico`: lista de (mes_referencia, slot_id, [nomes na ocorrência]).
    `genero`: nome -> "M"/"F" para TODO nome que aparece em `historico`.
    """
    genero_incerto = genero_incerto or {}
    dirigentes_pool = dirigentes_pool or []
    vigencia_inicio_fixos = vigencia_inicio_fixos or date.today()

    slots_por_pessoa = _construir_disponibilidades(historico)
    fixos_candidatos = _detectar_fixos(historico, fixo_fracao_minima, fixo_meses_minimos)
    ultimo_mes = _ultimo_mes_por_pessoa(historico)

    nomes_sem_genero = sorted(set(slots_por_pessoa) - set(genero))
    if nomes_sem_genero:
        raise ValueError(f"Nomes sem gênero em `genero`: {nomes_sem_genero}")

    pessoas_criadas_m = 0
    pessoas_criadas_f = 0
    nome_para_id: dict[str, int] = {}

    pessoas_existentes = {p.nome.strip().lower(): p for p in pessoas_repo.listar(conn)}

    for nome in sorted(slots_por_pessoa):
        genero_pessoa = genero[nome]
        chave = nome.strip().lower()
        pessoa = pessoas_existentes.get(chave)
        if pessoa is None:
            observacao = genero_incerto.get(nome)
            pessoa = pessoas_repo.criar(
                conn,
                PessoaIn(nome=nome, genero=genero_pessoa, observacoes=observacao),
            )
            pessoas_existentes[chave] = pessoa
            if genero_pessoa == "M":
                pessoas_criadas_m += 1
            else:
                pessoas_criadas_f += 1
        nome_para_id[nome] = pessoa.id

        slot_ids = sorted(slots_por_pessoa[nome])
        cadastro_service.definir_disponibilidade_pessoa(conn, pessoa.id, slot_ids)

    dirigentes_vinculados = _vincular_dirigentes(conn, dirigentes_pool, pessoas_existentes)

    fixos_aplicados = []
    for slot_id, nome, fracao, n_meses in fixos_candidatos:
        pessoa_id = nome_para_id[nome]
        ja_existe = conn.execute(
            """
            SELECT 1 FROM fixos
            WHERE slot_id = ? AND pessoa_id_1 = ? AND pessoa_id_2 IS NULL AND ativo = 1
            """,
            (slot_id, pessoa_id),
        ).fetchone()
        if ja_existe:
            fixos_aplicados.append((slot_id, nome, fracao, n_meses, "já existia"))
            continue
        cadastro_service.criar_fixo(
            conn,
            FixoIn(slot_id=slot_id, pessoa_id_1=pessoa_id, vigencia_inicio=vigencia_inicio_fixos),
        )
        fixos_aplicados.append((slot_id, nome, fracao, n_meses, "criado"))

    total_pessoas = len(slots_por_pessoa)
    total_m = sum(1 for nome in slots_por_pessoa if genero[nome] == "M")
    total_f = sum(1 for nome in slots_por_pessoa if genero[nome] == "F")
    possiveis_inativos = []
    if mes_limite_inativos:
        possiveis_inativos = sorted(
            nome for nome, mes in ultimo_mes.items() if mes <= mes_limite_inativos
        )

    return {
        "total_pessoas": total_pessoas,
        "total_m": total_m,
        "total_f": total_f,
        "pessoas_criadas_m": pessoas_criadas_m,
        "pessoas_criadas_f": pessoas_criadas_f,
        "dirigentes_vinculados": dirigentes_vinculados,
        "fixos_aplicados": fixos_aplicados,
        "genero_incerto": {n: {"genero": genero[n], "motivo": m} for n, m in genero_incerto.items()},
        "possiveis_inativos": [(nome, ultimo_mes[nome]) for nome in possiveis_inativos],
        "mes_limite_inativos": mes_limite_inativos,
    }


def formatar_relatorio(r: dict) -> str:
    linhas = []
    linhas.append("=" * 70)
    linhas.append("RELATÓRIO DA IMPORTAÇÃO DE HISTÓRICO")
    linhas.append("=" * 70)
    linhas.append(f"Pessoas cadastradas/atualizadas: {r['total_pessoas']} (M={r['total_m']}, F={r['total_f']})")
    linhas.append(f"  -> novas criadas nesta execução: M={r['pessoas_criadas_m']}, F={r['pessoas_criadas_f']}")
    linhas.append("")
    linhas.append("Dirigentes de campo:")
    if r["dirigentes_vinculados"]:
        for nome, status in r["dirigentes_vinculados"]:
            linhas.append(f"  - {nome}: {status}")
    else:
        linhas.append("  (nenhum pool de dirigentes informado)")
    linhas.append("")
    linhas.append("Fixos aplicados:")
    if r["fixos_aplicados"]:
        for slot_id, nome, fracao, n_meses, status in r["fixos_aplicados"]:
            linhas.append(f"  - {nome} -> {slot_id} (presente em {fracao:.0%} das ocorrências, {n_meses} meses) [{status}]")
    else:
        linhas.append("  (nenhum fixo atingiu os limiares de confiança)")
    linhas.append("")
    linhas.append("Nomes com gênero incerto (cadastrados com a melhor estimativa):")
    if r["genero_incerto"]:
        for nome, info in r["genero_incerto"].items():
            linhas.append(f"  - {nome} ({info['genero']}): {info['motivo']}")
    else:
        linhas.append("  (nenhum)")
    if r["mes_limite_inativos"]:
        linhas.append("")
        linhas.append(
            f"Pessoas cuja última aparição foi até {r['mes_limite_inativos']} "
            "(possíveis inativos, NÃO inativados automaticamente):"
        )
        if r["possiveis_inativos"]:
            for nome, mes in r["possiveis_inativos"]:
                linhas.append(f"  - {nome} (última aparição: {mes})")
        else:
            linhas.append("  (nenhum)")
    linhas.append("=" * 70)
    return "\n".join(linhas)
