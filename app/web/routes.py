from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import i18n
from app.api.deps import get_conn
from app.config import DIAS_SEMANA_ORDEM, TEMPLATES_DIR
from app.models import (
    BloqueioIn,
    FixoIn,
    PessoaIn,
    SaidaCampoTemplateIn,
    SlotTipoIn,
)
from app.pdf.pdf_generator import gerar_pdf_escala
from app.repositories import (
    bloqueios_repo,
    configuracoes_repo,
    disponibilidades_repo,
    fixos_repo,
    pessoas_repo,
    saida_repo,
    slots_repo,
)
from app.services import cadastro_service, escala_service

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

PERIODOS_SAIDA = ["MANHA", "TARDE"]
ASSISTENTE_TOTAL_PASSOS = 5


def _campo(form, nome: str) -> str:
    valor = form.get(nome)
    if valor is None or valor == "":
        raise HTTPException(status_code=400, detail=f"Campo obrigatório ausente: {nome}")
    return valor


def _campo_int(form, nome: str) -> int:
    valor = _campo(form, nome)
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Campo inválido (esperado número): {nome}")


def _campo_data(form, nome: str) -> date:
    valor = _campo(form, nome)
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Campo inválido (esperado data AAAA-MM-DD): {nome}")


def _campo_int_opcional(form, nome: str) -> int | None:
    valor = form.get(nome)
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Campo inválido (esperado número): {nome}")


# --- i18n: idioma atual + render() ------------------------------------------

def _idioma_atual(conn) -> str:
    return configuracoes_repo.obter(conn, "idioma", i18n.IDIOMA_PADRAO)


def render(nome_template: str, request: Request, conn, status_code: int = 200, **contexto):
    idioma = contexto.pop("idioma", None) or _idioma_atual(conn)
    contexto["request"] = request
    contexto["t"] = lambda chave, **kw: i18n.t(idioma, chave, **kw)
    contexto["t_aviso"] = lambda a: i18n.render_aviso(idioma, a)
    contexto["idioma_atual"] = idioma
    contexto["rtl"] = idioma in i18n.IDIOMAS_RTL
    contexto["idiomas_disponiveis"] = i18n.IDIOMAS
    contexto["nome_congregacao"] = configuracoes_repo.obter(conn, "nome_congregacao", "") or ""
    return templates.TemplateResponse(nome_template, contexto, status_code=status_code)


def _dias_semana_label(idioma: str) -> dict[str, str]:
    return {d: i18n.t(idioma, f"dias.{d.lower()}") for d in DIAS_SEMANA_ORDEM}


def _meses_label(idioma: str) -> dict[int, str]:
    return {m: i18n.t(idioma, f"meses.{m}") for m in range(1, 13)}


def _periodo_label(periodo, idioma: str) -> str:
    valor = getattr(periodo, "value", periodo)
    return i18n.t(idioma, "comum.manha" if valor == "MANHA" else "comum.tarde")


def _slot_label(slot, idioma: str) -> str:
    dia = i18n.t(idioma, f"dias.{slot.dia_semana.lower()}")
    return f"{dia} - {_periodo_label(slot.periodo, idioma)} - {slot.local}"


def _saida_label(saida, idioma: str) -> str:
    dia = i18n.t(idioma, f"dias.{saida.dia_semana.lower()}")
    rotulo = f"{dia} - {_periodo_label(saida.periodo, idioma)}"
    if saida.local:
        rotulo += f" - {saida.local}"
    return rotulo


def _slots_ordenados(conn):
    slots = slots_repo.listar(conn, somente_ativos=True)
    ordem = {d: i for i, d in enumerate(DIAS_SEMANA_ORDEM)}
    return sorted(slots, key=lambda s: (ordem.get(s.dia_semana, 99), s.ordem))


def _saidas_ordenadas(conn):
    saidas = saida_repo.listar(conn)
    ordem = {d: i for i, d in enumerate(DIAS_SEMANA_ORDEM)}
    return sorted(saidas, key=lambda s: (ordem.get(s.dia_semana, 99), s.ordem))


# --- escala (home) ----------------------------------------------------------

@router.get("/")
def home(conn=Depends(get_conn)):
    if configuracoes_repo.obter(conn, "wizard_concluido", "0") != "1":
        return RedirectResponse(url="/assistente")
    hoje = date.today()
    return RedirectResponse(url=f"/escala?ano={hoje.year}&mes={hoje.month}")


@router.get("/escala")
def pagina_escala(request: Request, ano: int, mes: int, erro: str | None = None, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    mes_referencia = escala_service.mes_referencia_str(ano, mes)
    escala = escala_service.obter_escala(conn, mes_referencia)
    pessoas = {p.id: p for p in pessoas_repo.listar(conn)}
    slots = {s.slot_id: s for s in slots_repo.listar(conn)}
    saidas_por_id = {s.saida_id: _saida_label(s, idioma) for s in saida_repo.listar(conn)}
    dirigentes = pessoas_repo.listar_dirigentes(conn, somente_ativos=True)

    linhas = []
    for d in escala.designacoes:
        slot = slots.get(d.slot_id)
        linhas.append({
            "id": d.id,
            "data": d.data,
            "slot_label": _slot_label(slot, idioma) if slot else d.slot_id,
            "pessoa_1": pessoas[d.pessoa_id_1].nome if d.pessoa_id_1 in pessoas else "",
            "pessoa_2": pessoas[d.pessoa_id_2].nome if d.pessoa_id_2 in pessoas else "",
            "pessoa_id_1": d.pessoa_id_1,
            "pessoa_id_2": d.pessoa_id_2,
            "origem": d.origem.value,
        })

    linhas_saidas = []
    for ds in escala.designacoes_saidas:
        linhas_saidas.append({
            "id": ds.id,
            "data": ds.data,
            "saida_label": saidas_por_id.get(ds.saida_id, ds.saida_id),
            "dirigente_id": ds.dirigente_id,
            "dirigente_nome": pessoas[ds.dirigente_id].nome if ds.dirigente_id in pessoas else "",
        })

    status = "fechado" if escala.designacoes and escala.designacoes[0].status == "FECHADO" else "rascunho"

    return render("escala.html", request, conn, idioma=idioma,
        ano=ano,
        mes=mes,
        mes_nome=i18n.t(idioma, f"meses.{mes}"),
        mes_referencia=mes_referencia,
        linhas=linhas,
        linhas_saidas=linhas_saidas,
        avisos=escala.avisos,
        pessoas=sorted(pessoas.values(), key=lambda p: p.nome),
        dirigentes=sorted(dirigentes, key=lambda d: d.nome),
        status=status,
        meses_label=_meses_label(idioma),
        erro=erro,
    )


@router.post("/escala/gerar")
async def gerar_escala(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    ano = _campo_int(form, "ano")
    mes = _campo_int(form, "mes")
    escala_service.gerar_rascunho(conn, ano, mes, date.today())
    return RedirectResponse(url=f"/escala?ano={ano}&mes={mes}", status_code=303)


@router.post("/escala/designacao/{designacao_id}/editar")
async def editar_designacao(designacao_id: int, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    ano, mes = _campo_int(form, "ano"), _campo_int(form, "mes")
    p1 = _campo_int_opcional(form, "pessoa_id_1")
    p2 = _campo_int_opcional(form, "pessoa_id_2")
    ok = escala_service.editar_designacao(conn, designacao_id, p1, p2)
    url = f"/escala?ano={ano}&mes={mes}"
    if not ok:
        url += "&erro=nao_editavel"
    return RedirectResponse(url=url, status_code=303)


@router.post("/escala/saida/{designacao_id}/editar")
async def editar_designacao_saida(designacao_id: int, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    ano, mes = _campo_int(form, "ano"), _campo_int(form, "mes")
    dirigente_id = _campo_int_opcional(form, "dirigente_id")
    ok = escala_service.editar_designacao_saida(conn, designacao_id, dirigente_id)
    url = f"/escala?ano={ano}&mes={mes}"
    if not ok:
        url += "&erro=nao_editavel"
    return RedirectResponse(url=url, status_code=303)


@router.post("/escala/fechar")
async def fechar_escala(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    ano, mes = _campo_int(form, "ano"), _campo_int(form, "mes")
    escala_service.fechar_mes(conn, escala_service.mes_referencia_str(ano, mes))
    return RedirectResponse(url=f"/escala?ano={ano}&mes={mes}", status_code=303)


@router.get("/escala/pdf")
def exportar_pdf(ano: int, mes: int, conn=Depends(get_conn)):
    dados = escala_service.montar_dados_pdf(conn, ano, mes)
    gerar_pdf_escala(
        dados.mes_referencia,
        dados.designacoes,
        dados.designacoes_dirigentes,
        dados.slots,
        dados.bloqueios,
        dados.pessoas_por_id,
        dados.dirigentes_por_id,
        dados.caminho,
    )
    return FileResponse(dados.caminho, filename=dados.caminho.name, media_type="application/pdf")


# --- pessoas ----------------------------------------------------------------

@router.get("/pessoas")
def pagina_pessoas(request: Request, conn=Depends(get_conn)):
    pessoas = pessoas_repo.listar(conn)
    nomes_por_id = {p.id: p.nome for p in pessoas}
    return render("pessoas.html", request, conn, pessoas=pessoas, nomes_por_id=nomes_por_id)


@router.post("/pessoas")
async def criar_pessoa(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    pessoas_repo.criar(conn, PessoaIn(
        nome=_campo(form, "nome"), genero=_campo(form, "genero"),
        telefone=form.get("telefone") or None, observacoes=form.get("observacoes") or None,
    ))
    return RedirectResponse(url="/pessoas", status_code=303)


@router.get("/pessoas/{pessoa_id}/editar")
def editar_pessoa_form(pessoa_id: int, request: Request, conn=Depends(get_conn)):
    pessoa = pessoas_repo.obter(conn, pessoa_id)
    genero_oposto = "F" if pessoa.genero.value == "M" else "M"
    pessoas_conjuge = [
        p for p in pessoas_repo.listar(conn)
        if p.id != pessoa_id and p.genero.value == genero_oposto
    ]
    return render("pessoa_editar.html", request, conn, pessoa=pessoa, pessoas=pessoas_conjuge)


@router.post("/pessoas/{pessoa_id}/editar")
async def editar_pessoa(pessoa_id: int, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    pessoas_repo.atualizar(conn, pessoa_id, PessoaIn(
        nome=_campo(form, "nome"), genero=_campo(form, "genero"), ativo="ativo" in form,
        telefone=form.get("telefone") or None, observacoes=form.get("observacoes") or None,
        pode_dirigir="pode_dirigir" in form,
    ))
    conjuge_id = _campo_int_opcional(form, "conjuge_id")
    cadastro_service.definir_conjuge(conn, pessoa_id, conjuge_id)
    return RedirectResponse(url="/pessoas", status_code=303)


@router.post("/pessoas/{pessoa_id}/inativar")
def inativar_pessoa(pessoa_id: int, conn=Depends(get_conn)):
    pessoas_repo.inativar(conn, pessoa_id)
    return RedirectResponse(url="/pessoas", status_code=303)


# --- disponibilidade ---------------------------------------------------------

@router.get("/disponibilidade")
def pagina_disponibilidade(request: Request, pessoa_id: int | None = None, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    pessoas = pessoas_repo.listar(conn, somente_ativos=True)
    slots = _slots_ordenados(conn)
    selecionados = set()
    if pessoa_id:
        selecionados = set(disponibilidades_repo.listar_slots_da_pessoa(conn, pessoa_id))
    return render("disponibilidade.html", request, conn, idioma=idioma,
        pessoas=pessoas, slots=slots, pessoa_id=pessoa_id, selecionados=selecionados,
        slot_label=lambda s: _slot_label(s, idioma),
    )


@router.post("/disponibilidade")
async def salvar_disponibilidade(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    pessoa_id = _campo_int(form, "pessoa_id")
    slot_ids = form.getlist("slot_ids")
    cadastro_service.definir_disponibilidade_pessoa(conn, pessoa_id, slot_ids)
    return RedirectResponse(url=f"/disponibilidade?pessoa_id={pessoa_id}", status_code=303)


# --- fixos --------------------------------------------------------------

@router.get("/fixos")
def pagina_fixos(request: Request, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    fixos = fixos_repo.listar(conn)
    pessoas = {p.id: p for p in pessoas_repo.listar(conn)}
    slots = {s.slot_id: s for s in slots_repo.listar(conn)}
    linhas = [{
        "fixo_id": f.fixo_id,
        "slot_label": _slot_label(slots[f.slot_id], idioma) if f.slot_id in slots else f.slot_id,
        "pessoa_1": pessoas[f.pessoa_id_1].nome if f.pessoa_id_1 in pessoas else "?",
        "pessoa_2": pessoas[f.pessoa_id_2].nome if f.pessoa_id_2 in pessoas else "",
        "vigencia_inicio": f.vigencia_inicio,
        "vigencia_fim": f.vigencia_fim,
        "ativo": f.ativo,
    } for f in fixos]
    return render("fixos.html", request, conn, idioma=idioma,
        linhas=linhas, pessoas=sorted(pessoas.values(), key=lambda p: p.nome),
        slots=_slots_ordenados(conn), slot_label=lambda s: _slot_label(s, idioma),
    )


@router.post("/fixos")
async def criar_fixo(request: Request, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    form = await request.form()
    erro = None
    try:
        cadastro_service.criar_fixo(conn, FixoIn(
            slot_id=_campo(form, "slot_id"),
            pessoa_id_1=_campo_int(form, "pessoa_id_1"),
            pessoa_id_2=_campo_int_opcional(form, "pessoa_id_2"),
            vigencia_inicio=_campo_data(form, "vigencia_inicio"),
        ))
    except ValueError as e:
        erro = str(e)
    if erro:
        pessoas = pessoas_repo.listar(conn)
        return render("fixos.html", request, conn, idioma=idioma, status_code=400,
            linhas=[], pessoas=pessoas, slots=_slots_ordenados(conn),
            slot_label=lambda s: _slot_label(s, idioma), erro=erro,
        )
    return RedirectResponse(url="/fixos", status_code=303)


@router.post("/fixos/{fixo_id}/encerrar")
def encerrar_fixo(fixo_id: int, conn=Depends(get_conn)):
    fixos_repo.encerrar_vigencia(conn, fixo_id, date.today())
    return RedirectResponse(url="/fixos", status_code=303)


# --- dirigentes (disponibilidade por saída de campo) -------------------------

@router.get("/dirigentes")
def pagina_dirigentes(request: Request, pessoa_id: int | None = None, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    dirigentes = pessoas_repo.listar_dirigentes(conn, somente_ativos=True)
    saidas = _saidas_ordenadas(conn)
    selecionados = set()
    if pessoa_id:
        selecionados = set(saida_repo.listar_saidas_do_dirigente(conn, pessoa_id))
    return render("dirigentes.html", request, conn, idioma=idioma,
        dirigentes=sorted(dirigentes, key=lambda d: d.nome),
        saidas=saidas, pessoa_id=pessoa_id, selecionados=selecionados,
        saida_label=lambda s: _saida_label(s, idioma),
    )


@router.post("/dirigentes/{pessoa_id}/disponibilidade")
async def salvar_disponibilidade_dirigente(pessoa_id: int, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    saida_ids = form.getlist("saida_ids")
    saida_repo.definir_disponibilidade_do_dirigente(conn, pessoa_id, saida_ids)
    return RedirectResponse(url=f"/dirigentes?pessoa_id={pessoa_id}", status_code=303)


# --- saídas de campo (template) ----------------------------------------------

@router.get("/saidas")
def pagina_saidas(request: Request, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    saidas = _saidas_ordenadas(conn)
    grade_marcados = {f"{s.dia_semana}:{s.periodo.value}" for s in saidas if s.ativo}
    return render("saidas.html", request, conn, idioma=idioma,
        saidas=saidas, dias_semana=DIAS_SEMANA_ORDEM,
        dias_semana_label=_dias_semana_label(idioma), periodos_saida=PERIODOS_SAIDA,
        periodos_saida_label={"MANHA": i18n.t(idioma, "comum.manha"), "TARDE": i18n.t(idioma, "comum.tarde")},
        grade_marcados=grade_marcados,
    )


@router.post("/saidas/grade")
async def salvar_grade_saidas(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    marcados = set(form.getlist("celula"))
    hoje = date.today()
    ordem_dia = {d: i for i, d in enumerate(DIAS_SEMANA_ORDEM)}
    por_dia_periodo: dict[tuple[str, str], list] = {}
    for s in saida_repo.listar(conn):
        por_dia_periodo.setdefault((s.dia_semana, s.periodo.value), []).append(s)

    for dia in DIAS_SEMANA_ORDEM:
        for periodo in PERIODOS_SAIDA:
            existentes = por_dia_periodo.get((dia, periodo), [])
            ativos = [s for s in existentes if s.ativo]
            marcado = f"{dia}:{periodo}" in marcados
            if marcado and not ativos:
                # reativa a saída já existente (qualquer saida_id) para esse dia+período,
                # em vez de criar duplicata, para não perder local/ordem/vigência configurados
                inativa_existente = existentes[0] if existentes else None
                if inativa_existente:
                    saida_repo.atualizar(conn, inativa_existente.saida_id, SaidaCampoTemplateIn(
                        saida_id=inativa_existente.saida_id, dia_semana=dia, periodo=periodo,
                        local=inativa_existente.local, ordem=inativa_existente.ordem,
                        vigencia_inicio=inativa_existente.vigencia_inicio,
                        vigencia_fim=inativa_existente.vigencia_fim, ativo=True,
                    ))
                else:
                    saida_id = f"{dia}_{periodo}"
                    saida_repo.criar(conn, SaidaCampoTemplateIn(
                        saida_id=saida_id, dia_semana=dia, periodo=periodo, local="",
                        ordem=ordem_dia[dia] * 10 + (0 if periodo == "MANHA" else 5),
                        vigencia_inicio=hoje,
                    ))
            elif not marcado and ativos:
                for s in ativos:
                    saida_repo.atualizar(conn, s.saida_id, SaidaCampoTemplateIn(
                        saida_id=s.saida_id, dia_semana=s.dia_semana, periodo=s.periodo,
                        local=s.local, ordem=s.ordem, vigencia_inicio=s.vigencia_inicio,
                        vigencia_fim=s.vigencia_fim, ativo=False,
                    ))
    return RedirectResponse(url="/saidas", status_code=303)


@router.post("/saidas")
async def criar_saida(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    saida_repo.criar(conn, SaidaCampoTemplateIn(
        saida_id=_campo(form, "saida_id"), dia_semana=_campo(form, "dia_semana"),
        periodo=_campo(form, "periodo"), local=form.get("local") or "",
        ordem=_campo_int(form, "ordem"), vigencia_inicio=_campo_data(form, "vigencia_inicio"),
    ))
    return RedirectResponse(url="/saidas", status_code=303)


@router.post("/saidas/{saida_id}/editar")
async def editar_saida(saida_id: str, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    atual = saida_repo.obter(conn, saida_id)
    saida_repo.atualizar(conn, saida_id, SaidaCampoTemplateIn(
        saida_id=saida_id, dia_semana=_campo(form, "dia_semana"), periodo=_campo(form, "periodo"),
        local=form.get("local") or "", ordem=_campo_int(form, "ordem"),
        vigencia_inicio=atual.vigencia_inicio, ativo="ativo" in form,
    ))
    return RedirectResponse(url="/saidas", status_code=303)


# --- slots (template semanal) -------------------------------------------------

@router.get("/slots")
def pagina_slots(request: Request, conn=Depends(get_conn)):
    idioma = _idioma_atual(conn)
    slots = _slots_ordenados(conn)
    return render("slots.html", request, conn, idioma=idioma,
        slots=slots, dias_semana=DIAS_SEMANA_ORDEM, dias_semana_label=_dias_semana_label(idioma),
    )


@router.post("/slots")
async def criar_slot(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    slots_repo.criar(conn, SlotTipoIn(
        slot_id=_campo(form, "slot_id"), dia_semana=_campo(form, "dia_semana"), periodo=_campo(form, "periodo"),
        local=_campo(form, "local"), ordem=_campo_int(form, "ordem"), requer_dirigente="requer_dirigente" in form,
        vigencia_inicio=_campo_data(form, "vigencia_inicio"),
    ))
    return RedirectResponse(url="/slots", status_code=303)


@router.post("/slots/{slot_id}/editar")
async def editar_slot(slot_id: str, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    atual = slots_repo.obter(conn, slot_id)
    slots_repo.atualizar(conn, slot_id, SlotTipoIn(
        slot_id=slot_id, dia_semana=_campo(form, "dia_semana"), periodo=_campo(form, "periodo"),
        local=_campo(form, "local"), ordem=_campo_int(form, "ordem"), requer_dirigente="requer_dirigente" in form,
        vigencia_inicio=atual.vigencia_inicio, ativo="ativo" in form,
    ))
    return RedirectResponse(url="/slots", status_code=303)


# --- bloqueios --------------------------------------------------------------

@router.get("/bloqueios")
def pagina_bloqueios(request: Request, conn=Depends(get_conn)):
    bloqueios = bloqueios_repo.listar(conn)
    return render("bloqueios.html", request, conn, bloqueios=bloqueios)


@router.post("/bloqueios")
async def criar_bloqueio(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    bloqueios_repo.criar(conn, BloqueioIn(
        data_inicio=_campo_data(form, "data_inicio"),
        data_fim=_campo_data(form, "data_fim"),
        motivo=form.get("motivo") or None,
    ))
    return RedirectResponse(url="/bloqueios", status_code=303)


@router.post("/bloqueios/{bloqueio_id}/remover")
def remover_bloqueio(bloqueio_id: int, conn=Depends(get_conn)):
    bloqueios_repo.remover(conn, bloqueio_id)
    return RedirectResponse(url="/bloqueios", status_code=303)


# --- configurações --------------------------------------------------------

@router.get("/configuracoes")
def pagina_configuracoes(request: Request, salvo: str | None = None, conn=Depends(get_conn)):
    return render("configuracoes.html", request, conn, salvo=salvo)


@router.post("/configuracoes")
async def salvar_configuracoes(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    configuracoes_repo.definir(conn, "nome_congregacao", _campo(form, "nome_congregacao"))
    configuracoes_repo.definir(conn, "idioma", _campo(form, "idioma"))
    return RedirectResponse(url="/configuracoes?salvo=1", status_code=303)


# --- assistente de configuração (wizard) --------------------------------------

@router.get("/assistente")
def pagina_assistente(request: Request, passo: int = 1, conn=Depends(get_conn)):
    passo = max(1, min(passo, ASSISTENTE_TOTAL_PASSOS))
    return render("assistente.html", request, conn, passo=passo, total_passos=ASSISTENTE_TOTAL_PASSOS)


@router.post("/assistente/passo1")
async def assistente_passo1(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    configuracoes_repo.definir(conn, "nome_congregacao", _campo(form, "nome_congregacao"))
    configuracoes_repo.definir(conn, "idioma", _campo(form, "idioma"))
    return RedirectResponse(url="/assistente?passo=2", status_code=303)


@router.post("/assistente/concluir")
def assistente_concluir(conn=Depends(get_conn)):
    configuracoes_repo.definir(conn, "wizard_concluido", "1")
    return RedirectResponse(url="/escala", status_code=303)
