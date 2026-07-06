from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app import i18n
from app.engine.calendar_utils import SaidaInstancia, SlotInstancia
from app.engine.scoring import chave_prioridade
from app.models import (
    Aviso,
    DesignacaoCarrinho,
    DesignacaoDirigente,
    DesignacaoSaida,
    Origem,
    StatusEscala,
)


def _aviso(nivel: str, chave: str, prefixo: str = "", **parametros) -> Aviso:
    """Constrói um Aviso com chave de tradução (ver app/i18n.py). `mensagem`
    é preenchida em pt-BR como fallback para quem ainda lê o texto fixo."""
    mensagem = i18n.t(i18n.IDIOMA_PADRAO, chave, **parametros)
    if prefixo:
        mensagem = f"{prefixo}: {mensagem}"
    return Aviso(nivel=nivel, mensagem=mensagem, chave=chave, parametros=parametros, prefixo=prefixo)


@dataclass
class ContextoSorteio:
    genero_por_pessoa: dict[int, str]
    ativos: set[int]
    disponibilidade_slot: dict[str, set[int]]
    fixos_por_slot: dict[str, tuple[int, Optional[int]]]
    ultima_designacao: dict[int, str]
    total_designacoes: dict[int, int]
    duplas_recentes: set[frozenset]

    dirigentes_ativos: set[int]
    disponibilidade_dirigente_slot: dict[str, set[int]]
    ultima_designacao_dirigente: dict[int, str]
    total_designacoes_dirigente: dict[int, int]

    # pessoa_id -> conjuge_id, apenas pessoas que têm cônjuge. Vínculo simétrico
    # (garantido pela camada de serviço). Casal é exceção válida à regra de mesmo gênero.
    # Default vazio: mantém compatível construção sem cônjuges (testes/chamadas posicionais).
    conjuge_de: dict[int, int] = field(default_factory=dict)

    # === Saída de campo (modelo novo) =====================================
    # dirigente É uma pessoa: pool = pessoas com pode_dirigir=1 e ativo=1.
    dirigentes_pool: set[int] = field(default_factory=set)
    # saida_id -> pessoa_ids disponíveis para aquela saída (fallback: pessoa do
    # pool SEM linha aqui = disponível para TODAS as saídas vigentes/ativas).
    disponibilidade_saida: dict[str, set[int]] = field(default_factory=dict)
    # rodízio de saída: mesma métrica de chave_prioridade, histórico próprio.
    ultima_saida: dict[int, str] = field(default_factory=dict)
    total_saidas: dict[int, int] = field(default_factory=dict)


@dataclass
class ResultadoSorteio:
    designacoes: list[DesignacaoCarrinho]
    designacoes_dirigentes: list[DesignacaoDirigente]
    avisos: list[Aviso]


def gerar_escala(
    instancias: list[SlotInstancia],
    ctx: ContextoSorteio,
    mes_referencia: str,
    hoje: date,
    bloqueio_carrinho: dict[tuple[str, str], set[int]] | None = None,
) -> ResultadoSorteio:
    # bloqueio_carrinho[(data_iso, periodo)] = pessoa_ids que servem como dirigente
    # de saída naquele dia/período e ficam bloqueadas no carrinho no MESMO período.
    if bloqueio_carrinho is None:
        bloqueio_carrinho = {}
    usados_no_mes: set[int] = set()
    duplas_usadas_no_mes: set[frozenset] = set()
    # contagem de designações já feitas NESTE sorteio (não vem do histórico em disco):
    # sem isso, quando várias pessoas empatam na prioridade histórica (comum no
    # primeiro mês, todas com zero designações), o desempate por ordem de iteração
    # de um `set` faria o sorteio repetir sempre as duas mesmas pessoas em todo slot
    # que caísse em fallback — este contador garante que o próprio sorteio se
    # auto-equilibre ao longo do mês.
    contagem_no_mes: dict[int, int] = {}
    # BUG #7: slots já avisados sobre gênero com só 1 disponível (1x por slot_id/execução)
    slots_genero_unico_avisados: set[str] = set()

    designacoes: list[DesignacaoCarrinho] = []
    # legado: o carrinho não gera mais dirigentes; sempre vazio (mantido p/ compat).
    designacoes_dirigentes: list[DesignacaoDirigente] = []
    avisos: list[Aviso] = []

    for inst in instancias:
        # pessoas bloqueadas neste slot: dirigentes de saída do mesmo dia/período.
        excluidos = bloqueio_carrinho.get((inst.data.isoformat(), inst.periodo), set())

        p1, p2, tem_fixo = _aplicar_fixo(inst, ctx, excluidos, avisos)

        if p1 is not None:
            usados_no_mes.add(p1)
        if p2 is not None:
            usados_no_mes.add(p2)

        origem = Origem.FIXO if tem_fixo else Origem.SORTEIO

        if p2 is None:
            if p1 is not None:
                genero_alvo = ctx.genero_por_pessoa.get(p1)
                parceiro, origem_sorteio, aviso = _completar_par(
                    inst.slot_id, genero_alvo, p1, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje,
                    excluidos=excluidos,
                )
                p2 = parceiro
                # a origem "FIXO" prevalece mesmo quando a outra vaga foi sorteada —
                # é o que define este slot como tendo uma pessoa fixa nele
                if not tem_fixo:
                    origem = origem_sorteio
            else:
                par, origem_sorteio, aviso = _resolver_slot_sem_fixo(
                    inst.slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje,
                    avisos=avisos, prefixo_aviso=f"{inst.data.isoformat()} ({inst.slot_id})",
                    slots_genero_unico_avisados=slots_genero_unico_avisados,
                    excluidos=excluidos,
                )
                if par:
                    p1, p2 = par
                origem = origem_sorteio

            if aviso:
                nivel, chave, params = aviso
                avisos.append(_aviso(nivel, chave, prefixo=f"{inst.data.isoformat()} ({inst.slot_id})", **params))

        if p1 is None and p2 is None:
            origem = Origem.VAZIO
        _registrar_uso(p1, p2, usados_no_mes, contagem_no_mes, duplas_usadas_no_mes)

        designacoes.append(
            DesignacaoCarrinho(
                data=inst.data,
                slot_id=inst.slot_id,
                pessoa_id_1=p1,
                pessoa_id_2=p2,
                origem=origem,
                mes_referencia=mes_referencia,
                status=StatusEscala.RASCUNHO,
            )
        )

    return ResultadoSorteio(designacoes, designacoes_dirigentes, avisos)


# --- helpers: fixos e estado do loop ---------------------------------------

def _aplicar_fixo(inst, ctx: ContextoSorteio, excluidos, avisos) -> tuple[Optional[int], Optional[int], bool]:
    """Encapsula a lógica de fixos de um slot: lê ctx.fixos_por_slot, valida cada
    pessoa fixa contra ctx.ativos (BUG#4) e contra excluidos (bloqueio de dirigente
    de saída no mesmo período), normaliza o remanescente único para p1 e devolve
    (p1, p2, tem_fixo), acrescentando os mesmos avisos que o fluxo original."""
    p1: Optional[int] = None
    p2: Optional[int] = None

    fixo = ctx.fixos_por_slot.get(inst.slot_id)
    if fixo:
        f1, f2 = fixo
        # BUG #4: pessoa fixa inativa não pode ser escalada. Valida cada uma
        # contra ctx.ativos; a que estiver inativa é tratada como ausente e
        # gera aviso crítico. Se sobra a outra, ela vira remanescente (p1) e o
        # slot volta a precisar de complemento sorteado; se ambas inativas, o
        # slot cai no fluxo sem-fixo.
        prefixo = f"{inst.data.isoformat()} ({inst.slot_id})"
        if f1 is not None and f1 not in ctx.ativos:
            avisos.append(_aviso("critico", "aviso.fixo_inativo", prefixo=prefixo, slot=inst.slot_id))
            f1 = None
        if f2 is not None and f2 not in ctx.ativos:
            avisos.append(_aviso("critico", "aviso.fixo_inativo", prefixo=prefixo, slot=inst.slot_id))
            f2 = None
        # BUG #4 (variante bloqueio): fixo que também é dirigente de saída no mesmo
        # período não pode servir no carrinho — trata como ausente + aviso crítico.
        if f1 is not None and f1 in excluidos:
            avisos.append(_aviso("critico", "aviso.dirigente_bloqueia_fixo", prefixo=prefixo, pessoa_id=f1))
            f1 = None
        if f2 is not None and f2 in excluidos:
            avisos.append(_aviso("critico", "aviso.dirigente_bloqueia_fixo", prefixo=prefixo, pessoa_id=f2))
            f2 = None
        # normaliza: remanescente único vai para p1 (evita p1=None com p2 setado)
        if f1 is None and f2 is not None:
            f1, f2 = f2, None
        p1, p2 = f1, f2

    tem_fixo = p1 is not None
    return p1, p2, tem_fixo


def _registrar_uso(p1, p2, usados_no_mes: set[int], contagem_no_mes: dict[int, int], duplas_usadas_no_mes: set[frozenset]):
    """Atualização de estado pós-slot: marca p1/p2 como usados no mês, incrementa a
    contagem no mês e registra a dupla formada. Mesmo efeito do bloco original."""
    if p1:
        usados_no_mes.add(p1)
        contagem_no_mes[p1] = contagem_no_mes.get(p1, 0) + 1
    if p2:
        usados_no_mes.add(p2)
        contagem_no_mes[p2] = contagem_no_mes.get(p2, 0) + 1
    if p1 and p2:
        duplas_usadas_no_mes.add(frozenset((p1, p2)))


# --- helpers: pares do carrinho --------------------------------------------

def _pessoas_disponiveis(slot_id: str, genero: str, ctx: ContextoSorteio, excluidos: set[int] = frozenset()) -> set[int]:
    disponiveis = ctx.disponibilidade_slot.get(slot_id, set())
    return {p for p in disponiveis if p in ctx.ativos and p not in excluidos and ctx.genero_por_pessoa.get(p) == genero}


def _ordenar(pessoas, ctx: ContextoSorteio, contagem_no_mes: dict[int, int], hoje: date) -> list[int]:
    return sorted(
        pessoas,
        key=lambda p: (
            contagem_no_mes.get(p, 0),
            chave_prioridade(p, ctx.ultima_designacao, ctx.total_designacoes, hoje),
        ),
    )


def _dupla_proibida(p1: int, p2: int, ctx: ContextoSorteio, duplas_usadas_no_mes: set[frozenset]) -> bool:
    par = frozenset((p1, p2))
    return par in ctx.duplas_recentes or par in duplas_usadas_no_mes


def _completar_par(slot_id, genero_alvo, p1_fixo, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos: set[int] = frozenset()):
    if genero_alvo is None:
        return None, Origem.VAZIO, ("critico", "aviso.fixo_sem_genero", {})

    pool = _pessoas_disponiveis(slot_id, genero_alvo, ctx, excluidos) - {p1_fixo}

    candidatos = _ordenar(pool - usados_no_mes, ctx, contagem_no_mes, hoje)
    for c in candidatos:
        if not _dupla_proibida(p1_fixo, c, ctx, duplas_usadas_no_mes):
            return c, Origem.SORTEIO, None

    # BUG #5: antes de aceitar par repetido, tenta o pool completo (inclui quem já
    # foi usado no mês). Se existe complemento não-proibido, prefira-o — melhor
    # reusar alguém do mês do que repetir uma dupla proibida dos últimos meses.
    candidatos_todos = _ordenar(pool, ctx, contagem_no_mes, hoje)
    for c in candidatos_todos:
        if not _dupla_proibida(p1_fixo, c, ctx, duplas_usadas_no_mes):
            # se c ainda não foi usado no mês é SORTEIO puro; se já foi, é reuso no mês
            if c not in usados_no_mes:
                return c, Origem.SORTEIO, None
            return c, Origem.FALLBACK_DUPLICADO, ("atencao", "aviso.fallback_duplicado", {})

    if candidatos:
        return candidatos[0], Origem.FALLBACK_PAR_REPETIDO, ("atencao", "aviso.fallback_dupla_repetida", {})

    if candidatos_todos:
        return candidatos_todos[0], Origem.FALLBACK_DUPLICADO, ("atencao", "aviso.fallback_duplicado", {})

    return None, Origem.VAZIO, ("critico", "aviso.dupla_incompleta_vazio", {})


def _primeira_combinacao_permitida(candidatos_ordenados, ctx, duplas_usadas_no_mes):
    for i, p1 in enumerate(candidatos_ordenados):
        for p2 in candidatos_ordenados[i + 1:]:
            if not _dupla_proibida(p1, p2, ctx, duplas_usadas_no_mes):
                return (p1, p2)
    return None


def _par_permitido_cruzando_pool(candidatos_nao_usados, candidatos_todos, ctx, duplas_usadas_no_mes):
    """BUG #5: procura par não-proibido cruzando os não-usados-no-mês (prioritários)
    com o pool completo ordenado, exigindo que ao menos um dos dois ainda não tenha
    sido usado no mês. Prefere minimizar reuso: retorna a primeira combinação (a lista
    já vem ordenada por prioridade)."""
    for p1 in candidatos_nao_usados:
        for p2 in candidatos_todos:
            if p2 == p1:
                continue
            if not _dupla_proibida(p1, p2, ctx, duplas_usadas_no_mes):
                return (p1, p2)
    return None


def _formar_dupla(slot_id, genero, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos: set[int] = frozenset()):
    pool = _pessoas_disponiveis(slot_id, genero, ctx, excluidos)

    candidatos = _ordenar(pool - usados_no_mes, ctx, contagem_no_mes, hoje)
    par = _primeira_combinacao_permitida(candidatos, ctx, duplas_usadas_no_mes)
    if par:
        return par, Origem.SORTEIO, None

    candidatos_todos = _ordenar(pool, ctx, contagem_no_mes, hoje)

    # BUG #5: antes de aceitar par repetido, tenta par não-proibido cruzando um
    # candidato não usado no mês com o pool completo (reuso de mês é preferível a
    # repetir dupla proibida dos últimos meses).
    par_cruzado = _par_permitido_cruzando_pool(candidatos, candidatos_todos, ctx, duplas_usadas_no_mes)
    if par_cruzado:
        return par_cruzado, Origem.SORTEIO, None

    if len(candidatos) >= 2:
        return (candidatos[0], candidatos[1]), Origem.FALLBACK_PAR_REPETIDO, ("atencao", "aviso.fallback_dupla_repetida", {})

    if len(candidatos_todos) >= 2:
        return (candidatos_todos[0], candidatos_todos[1]), Origem.FALLBACK_DUPLICADO, ("atencao", "aviso.fallback_duplicado", {})

    return None, Origem.VAZIO, ("critico", "aviso.menos_de_2_genero", {"genero": genero})


def _escolher_genero_para_slot(slot_id, ctx, usados_no_mes, contagem_no_mes, hoje, excluidos: set[int] = frozenset()):
    melhor_genero = None
    melhor_chave = None
    for genero in ("M", "F"):
        pool = _pessoas_disponiveis(slot_id, genero, ctx, excluidos) - usados_no_mes
        candidatos = _ordenar(pool, ctx, contagem_no_mes, hoje)
        if len(candidatos) < 2:
            continue
        chave = (contagem_no_mes.get(candidatos[0], 0), chave_prioridade(candidatos[0], ctx.ultima_designacao, ctx.total_designacoes, hoje))
        if melhor_chave is None or chave < melhor_chave:
            melhor_chave = chave
            melhor_genero = genero
    return melhor_genero


def _chave_par(par, ctx, contagem_no_mes, hoje):
    """Chave de prioridade de um par: usa a MENOR (melhor) chave dos dois membros,
    mesma métrica de _ordenar, para poder comparar dupla-casal com dupla mesmo-gênero."""
    def chave_pessoa(p):
        return (contagem_no_mes.get(p, 0), chave_prioridade(p, ctx.ultima_designacao, ctx.total_designacoes, hoje))
    return min(chave_pessoa(par[0]), chave_pessoa(par[1]))


def _melhor_par_casal(slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos: set[int] = frozenset()):
    """FEATURE CASAL: gera o melhor par-casal candidato para o slot. Ambos os cônjuges
    devem estar disponíveis no slot, ativos, não usados no mês, não bloqueados
    (dirigente de saída no mesmo período) e o par não proibido.
    Determinístico: itera pares (a,b) com a<b em ordem estável."""
    disponiveis = ctx.disponibilidade_slot.get(slot_id, set())
    melhor = None
    melhor_chave = None
    for a, b in _pares_casal_ordenados(ctx.conjuge_de):
        if a not in disponiveis or b not in disponiveis:
            continue
        if a in excluidos or b in excluidos:
            continue
        if a not in ctx.ativos or b not in ctx.ativos:
            continue
        if a in usados_no_mes or b in usados_no_mes:
            continue
        if _dupla_proibida(a, b, ctx, duplas_usadas_no_mes):
            continue
        chave = _chave_par((a, b), ctx, contagem_no_mes, hoje)
        if melhor_chave is None or chave < melhor_chave:
            melhor_chave = chave
            melhor = (a, b)
    return melhor, melhor_chave


def _pares_casal_ordenados(conjuge_de: dict[int, int]):
    """Pares casal únicos e ordenados de forma estável: cada casal aparece 1x como
    (min_id, max_id), independentemente da simetria do dict."""
    pares = set()
    for a, b in conjuge_de.items():
        if conjuge_de.get(b) == a:  # vínculo simétrico confirmado
            pares.add((min(a, b), max(a, b)))
    return sorted(pares)


def _melhor_dupla_mesmo_genero_limpa(slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos: set[int] = frozenset()):
    """Melhor dupla de mesmo gênero SEM fallback (ambos não usados no mês, par não
    proibido). Retorna (par, chave, genero) ou (None, None, None). Espelha a escolha
    de gênero por prioridade, mas devolve a chave para comparar com o par-casal."""
    melhor = None
    melhor_chave = None
    melhor_genero = None
    for genero in ("M", "F"):
        pool = _pessoas_disponiveis(slot_id, genero, ctx, excluidos)
        candidatos = _ordenar(pool - usados_no_mes, ctx, contagem_no_mes, hoje)
        par = _primeira_combinacao_permitida(candidatos, ctx, duplas_usadas_no_mes)
        if par is None:
            continue
        chave = _chave_par(par, ctx, contagem_no_mes, hoje)
        if melhor_chave is None or chave < melhor_chave:
            melhor_chave = chave
            melhor = par
            melhor_genero = genero
    return melhor, melhor_chave, melhor_genero


def _avisar_genero_unico(slot_id, ctx, usados_no_mes, contagem_no_mes, hoje, avisos, prefixo_aviso, slots_avisados, excluidos: set[int] = frozenset()):
    """BUG #7: se um gênero tem EXATAMENTE 1 candidato disponível no slot (não dá para
    formar dupla de mesmo gênero), emite aviso informativo 1x por slot_id/execução."""
    if avisos is None or slot_id in slots_avisados:
        return
    for genero in ("M", "F"):
        candidatos = _ordenar(_pessoas_disponiveis(slot_id, genero, ctx, excluidos) - usados_no_mes, ctx, contagem_no_mes, hoje)
        if len(candidatos) == 1:
            slots_avisados.add(slot_id)
            avisos.append(_aviso("atencao", "aviso.genero_unico_no_horario", prefixo=prefixo_aviso, genero=genero))
            return  # no máximo 1 aviso por slot


def _resolver_slot_sem_fixo(slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje,
                            avisos=None, prefixo_aviso="", slots_genero_unico_avisados=None,
                            excluidos: set[int] = frozenset()):
    if slots_genero_unico_avisados is None:
        slots_genero_unico_avisados = set()
    _avisar_genero_unico(slot_id, ctx, usados_no_mes, contagem_no_mes, hoje, avisos, prefixo_aviso, slots_genero_unico_avisados, excluidos)

    # FEATURE CASAL: compara o melhor par-casal (gênero misto permitido) com a melhor
    # dupla LIMPA de mesmo gênero, pela mesma chave de prioridade; vence a menor chave.
    # Só decide aqui quando o casal for melhor OU igual em vantagem clara; caso contrário
    # cai no fluxo normal (que preserva toda a cadeia de fallback existente).
    par_casal, chave_casal = _melhor_par_casal(slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos)
    if par_casal is not None:
        _, chave_mesmo_genero, _ = _melhor_dupla_mesmo_genero_limpa(
            slot_id, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos
        )
        if chave_mesmo_genero is None or chave_casal <= chave_mesmo_genero:
            return par_casal, Origem.SORTEIO, None

    genero_escolhido = _escolher_genero_para_slot(slot_id, ctx, usados_no_mes, contagem_no_mes, hoje, excluidos)
    generos_a_tentar = [genero_escolhido] if genero_escolhido else ["M", "F"]

    ultimo_resultado = (None, Origem.VAZIO, ("critico", "aviso.slot_vazio_sem_candidato", {}))
    for genero in generos_a_tentar:
        resultado = _formar_dupla(slot_id, genero, ctx, usados_no_mes, duplas_usadas_no_mes, contagem_no_mes, hoje, excluidos)
        if resultado[0] is not None:
            return resultado
        ultimo_resultado = resultado

    # Sem dupla de mesmo gênero viável: se existe par-casal (mesmo perdendo a chave
    # acima por empate/ordem), ele ainda é uma solução válida — prefira-o ao VAZIO.
    if ultimo_resultado[0] is None and par_casal is not None:
        return par_casal, Origem.SORTEIO, None

    return ultimo_resultado


# --- helpers: dirigente de campo -------------------------------------------

def _escolher_dirigente(slot_id, ctx: ContextoSorteio, usados_semana: set[int], contagem_dirigente_no_mes: dict[int, int], hoje: date):
    pool = ctx.disponibilidade_dirigente_slot.get(slot_id, set()) & ctx.dirigentes_ativos

    def chave(d):
        return (
            contagem_dirigente_no_mes.get(d, 0),
            chave_prioridade(d, ctx.ultima_designacao_dirigente, ctx.total_designacoes_dirigente, hoje),
        )

    candidatos = sorted(pool - usados_semana, key=chave)
    if candidatos:
        return candidatos[0], None

    candidatos_todos = sorted(pool, key=chave)
    if candidatos_todos:
        return candidatos_todos[0], ("atencao", "dirigente repetido na mesma semana por falta de outra opção")

    return None, ("critico", "nenhum dirigente disponível para esta sessão — preencher manualmente")


# --- saída de campo (modelo novo) ------------------------------------------

def _dirigentes_disponiveis_saida(saida_id: str, ctx: ContextoSorteio) -> set[int]:
    """Pool de dirigentes disponíveis para uma saída. FALLBACK: dirigente do pool
    SEM nenhuma linha em disponibilidade_saida está disponível para TODAS as saídas.
    Um dirigente com alguma linha só entra nas saídas em que aparece."""
    com_restricao = set().union(*ctx.disponibilidade_saida.values()) if ctx.disponibilidade_saida else set()
    explicitos = ctx.disponibilidade_saida.get(saida_id, set()) & ctx.dirigentes_pool
    sem_restricao = {d for d in ctx.dirigentes_pool if d not in com_restricao}
    return explicitos | sem_restricao


def gerar_saidas(
    instancias_saida: list[SaidaInstancia],
    ctx: ContextoSorteio,
    mes_referencia: str,
    hoje: date,
) -> tuple[list[DesignacaoSaida], dict[tuple[str, str], set[int]], list[Aviso]]:
    """Sorteia 1 dirigente por saída/dia, com rodízio (histórico próprio) e sem
    repetir dirigente na mesma semana ISO. Retorna as designações (RASCUNHO), o
    mapa de BLOQUEIO carrinho[(data_iso, periodo)] -> pessoa_ids designadas, e avisos.
    """
    designacoes: list[DesignacaoSaida] = []
    bloqueio: dict[tuple[str, str], set[int]] = {}
    avisos: list[Aviso] = []

    usados_na_semana: dict[int, set[int]] = {}
    contagem_no_mes: dict[int, int] = {}

    def chave(d):
        return (
            contagem_no_mes.get(d, 0),
            chave_prioridade(d, ctx.ultima_saida, ctx.total_saidas, hoje),
        )

    for inst in sorted(instancias_saida, key=lambda i: i.data):
        pool = _dirigentes_disponiveis_saida(inst.saida_id, ctx)
        semana = inst.data.isocalendar()[1]
        usados_semana = usados_na_semana.setdefault(semana, set())

        dirigente_id = None
        candidatos = sorted(pool - usados_semana, key=chave)
        if candidatos:
            dirigente_id = candidatos[0]
        else:
            candidatos_todos = sorted(pool, key=chave)
            prefixo = f"{inst.data.isoformat()} ({inst.saida_id})"
            if candidatos_todos:
                dirigente_id = candidatos_todos[0]
                avisos.append(_aviso("atencao", "aviso.dirigente_repetido_semana", prefixo=prefixo))
            else:
                avisos.append(_aviso("critico", "aviso.dirigente_indisponivel", prefixo=prefixo))

        if dirigente_id is not None:
            usados_semana.add(dirigente_id)
            contagem_no_mes[dirigente_id] = contagem_no_mes.get(dirigente_id, 0) + 1
            bloqueio.setdefault((inst.data.isoformat(), inst.periodo), set()).add(dirigente_id)

        designacoes.append(
            DesignacaoSaida(
                data=inst.data,
                saida_id=inst.saida_id,
                dirigente_id=dirigente_id,
                mes_referencia=mes_referencia,
                status=StatusEscala.RASCUNHO,
            )
        )

    return designacoes, bloqueio, avisos
